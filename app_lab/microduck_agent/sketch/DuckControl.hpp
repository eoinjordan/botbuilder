// SPDX-License-Identifier: MIT
//
// Command handling and motion control for the six-servo biped. Portable C++
// with no Arduino dependency, so the same file is compiled for the UNO Q and
// for the host test (tests/firmware_host.cpp). It is the C++ twin of
// microduck/protocol.py Controller; the tests feed both the same lines and
// compare the replies and the pulse widths.
//
// Soft limits: J targets are clamped to the joint limits of the table.
// Speed limit: the commanded angle moves at most max_speed_deg_s.
// Watchdog: in RUN, if no J line arrives for watchdog_ms the controller
// holds the current command (or relaxes, if set to).
// Hold: H makes the commanded angles of this instant the target, in one line.
// Calibration: C/N/Z/X move one joint by steps of at most step_max_deg.
// Leg clearance: per-joint limits cannot keep one leg out of the other, so
// the table carries boxes around each thigh and each shin with its sole. A J
// target or a calibration nudge that would bring the legs together is
// refused (ERR CLEAR), and a tick's step that would is not taken. The test
// uses its own sine and plain double arithmetic so that this file, the
// Python reference and the page's copy agree bit for bit; build it without
// fused multiply-add contraction (-ffp-contract=off).
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace duck {

constexpr int JOINTS = 6;
constexpr uint32_t TICK_MS = 20;

struct JointCal {
  const char *name;
  int pin;
  double zero_deg;
  int direction;      // +1 or -1
  double min_deg;
  double max_deg;
};

constexpr int MAX_BOXES = 8;

// Centre, half size and bounding radius of a box in its link frame, mm.
struct Box {
  double v[7];
};

// One leg for the clearance test: the origins of the hip roll, hip pitch and
// knee frames, each in its parent frame (mm), and the boxes of the thigh and
// of the shin. A leg with no shin box switches the test off.
struct LegShape {
  double origin[3][3];
  int thigh_count;
  Box thigh[MAX_BOXES];
  int shin_count;
  Box shin[MAX_BOXES];
};

struct Table {
  JointCal joints[JOINTS];
  int min_us;
  int max_us;
  int frequency_hz;
  int soft_start_pin;
  double max_speed_deg_s;
  uint32_t watchdog_ms;
  bool watchdog_relax;
  double step_max_deg;
  double stand_deg[JOINTS];
  LegShape legs[2];   // left, right
};

// --- leg clearance ----------------------------------------------------------
// Keep this block operation for operation the same as microduck/protocol.py.

namespace clearance {

constexpr double PI = 3.141592653589793;
constexpr double S3 = -0.16666666666666666, S5 = 0.008333333333333333, S7 = -0.0001984126984126984;
constexpr double S9 = 2.7557319223985893e-06, S11 = -2.505210838544172e-08, S13 = 1.6059043836821613e-10;

// Sine of an angle in degrees, the same arithmetic everywhere.
inline double sine(double deg) {
  double x = deg * (PI / 180.0);
  while (x > PI) x -= 2.0 * PI;
  while (x < -PI) x += 2.0 * PI;
  if (x > 0.5 * PI) x = PI - x;
  if (x < -0.5 * PI) x = -PI - x;
  const double x2 = x * x;
  return x * (1.0 + x2 * (S3 + x2 * (S5 + x2 * (S7 + x2 * (S9 + x2 * (S11 + x2 * S13))))));
}

inline double cosine(double deg) { return sine(deg + 90.0); }

// Rotation about x by roll, then about y by pitch; rows of the matrix.
inline void frame(double roll, double pitch, double m[3][3]) {
  const double sr = sine(roll), cr = cosine(roll), sp = sine(pitch), cp = cosine(pitch);
  m[0][0] = cp;       m[0][1] = 0.0; m[0][2] = sp;
  m[1][0] = sr * sp;  m[1][1] = cr;  m[1][2] = -sr * cp;
  m[2][0] = -cr * sp; m[2][1] = sr;  m[2][2] = cr * cp;
}

inline void apply(const double m[3][3], const double *v, double out[3]) {
  out[0] = m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2];
  out[1] = m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2];
  out[2] = m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2];
}

struct Pose {
  double thigh[3][3], p_thigh[3], shin[3][3], p_shin[3];
};

// Frames of the thigh and the shin in the torso frame, mm.
inline void leg(const LegShape &shape, double roll, double pitch, double knee, Pose &out) {
  double level[3][3], lifted[3], lowered[3];
  frame(roll, pitch, out.thigh);
  frame(roll, pitch + knee, out.shin);
  frame(roll, 0.0, level);
  apply(level, shape.origin[1], lifted);
  for (int k = 0; k < 3; k++) out.p_thigh[k] = shape.origin[0][k] + lifted[k];
  apply(out.thigh, shape.origin[2], lowered);
  for (int k = 0; k < 3; k++) out.p_shin[k] = out.p_thigh[k] + lowered[k];
}

// True when two boxes do not touch. Separating axis test.
inline bool apart(const double ra[3][3], const double *pa, const double *a,
                  const double rb[3][3], const double *pb, const double *b) {
  double ca[3], cb[3], d[3], r[3][3], f[3][3], t[3];
  apply(ra, a, ca);
  apply(rb, b, cb);
  for (int k = 0; k < 3; k++) d[k] = pb[k] + cb[k] - pa[k] - ca[k];
  const double reach = a[6] + b[6];
  if (d[0] * d[0] + d[1] * d[1] + d[2] * d[2] > reach * reach) return true;
  // b's axes and the offset in a's frame
  for (int i = 0; i < 3; i++) {
    for (int j = 0; j < 3; j++) {
      r[i][j] = ra[0][i] * rb[0][j] + ra[1][i] * rb[1][j] + ra[2][i] * rb[2][j];
      f[i][j] = (r[i][j] >= 0.0 ? r[i][j] : -r[i][j]) + 1e-9;
    }
  }
  for (int i = 0; i < 3; i++) t[i] = ra[0][i] * d[0] + ra[1][i] * d[1] + ra[2][i] * d[2];
  for (int i = 0; i < 3; i++) {
    const double s = t[i] >= 0.0 ? t[i] : -t[i];
    if (s > a[3 + i] + b[3] * f[i][0] + b[4] * f[i][1] + b[5] * f[i][2]) return true;
  }
  for (int j = 0; j < 3; j++) {
    double s = t[0] * r[0][j] + t[1] * r[1][j] + t[2] * r[2][j];
    if (s < 0.0) s = -s;
    if (s > a[3] * f[0][j] + a[4] * f[1][j] + a[5] * f[2][j] + b[3 + j]) return true;
  }
  for (int i = 0; i < 3; i++) {
    const int i1 = (i + 1) % 3, i2 = (i + 2) % 3;
    for (int j = 0; j < 3; j++) {
      const int j1 = (j + 1) % 3, j2 = (j + 2) % 3;
      double s = t[i2] * r[i1][j] - t[i1] * r[i2][j];
      if (s < 0.0) s = -s;
      if (s > a[3 + i1] * f[i2][j] + a[3 + i2] * f[i1][j] + b[3 + j1] * f[i][j2] + b[3 + j2] * f[i][j1]) return true;
    }
  }
  return false;
}

// True when no box of one leg touches a box of the other at joint angles q.
inline bool legsClear(const LegShape legs[2], const double *q) {
  const LegShape &left = legs[0];
  const LegShape &right = legs[1];
  if (left.shin_count == 0 || right.shin_count == 0) return true;
  Pose l, r;
  leg(left, q[0], q[1], q[2], l);
  leg(right, q[3], q[4], q[5], r);
  for (int i = 0; i < left.shin_count; i++) {
    for (int j = 0; j < right.shin_count; j++) {
      if (!apart(l.shin, l.p_shin, left.shin[i].v, r.shin, r.p_shin, right.shin[j].v)) return false;
    }
    for (int j = 0; j < right.thigh_count; j++) {
      if (!apart(l.shin, l.p_shin, left.shin[i].v, r.thigh, r.p_thigh, right.thigh[j].v)) return false;
    }
  }
  for (int i = 0; i < left.thigh_count; i++) {
    for (int j = 0; j < right.shin_count; j++) {
      if (!apart(l.thigh, l.p_thigh, left.thigh[i].v, r.shin, r.p_shin, right.shin[j].v)) return false;
    }
  }
  return true;
}

}  // namespace clearance

enum Mode { RELAX = 0, RUN = 1, HOLD = 2, CAL = 3 };

class Controller {
 public:
  explicit Controller(const Table &table) : table_(table) {
    for (int i = 0; i < JOINTS; i++) {
      current_[i] = target_[i] = table.stand_deg[i];
      zero_[i] = table.joints[i].zero_deg;
    }
    watchdog_ms_ = table.watchdog_ms;
    watchdog_relax_ = table.watchdog_relax;
  }

  Mode mode() const { return mode_; }
  double current(int i) const { return current_[i]; }

  double servoDeg(int i) const {
    return bound(zero_[i] + table_.joints[i].direction * current_[i], 0.0, 180.0);
  }

  // Pulse width in microseconds, or 0 for no pulse (relaxed).
  int pulseUs(int i) const {
    if (mode_ == RELAX) return 0;
    return pulseFor(servoDeg(i));
  }

  void tick(uint32_t now_ms) {
    if (mode_ == RUN && armed_ && static_cast<uint32_t>(now_ms - last_cmd_ms_) > watchdog_ms_) {
      if (watchdog_relax_) {
        mode_ = RELAX;
      } else {
        mode_ = HOLD;
        for (int i = 0; i < JOINTS; i++) target_[i] = current_[i];
      }
      armed_ = false;
    }
    if (mode_ != RUN) return;
    const double step = table_.max_speed_deg_s * TICK_MS / 1000.0;
    double next[JOINTS];
    for (int i = 0; i < JOINTS; i++) {
      next[i] = current_[i] + bound(target_[i] - current_[i], -step, step);
    }
    // a step that would bring the legs together is not taken
    if (clearance::legsClear(table_.legs, next)) {
      for (int i = 0; i < JOINTS; i++) current_[i] = next[i];
    }
  }

  // One command line in, one reply out (no newline). out must hold 128 chars.
  void handle(const char *line, uint32_t now_ms, char *out, size_t size) {
    Writer w(out, size);
    const char *tok[8];
    size_t len[8];
    int n = 0;
    const char *p = line;
    while (*p) {
      while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
      if (!*p) break;
      const char *start = p;
      while (*p && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') p++;
      if (n < 8) {
        tok[n] = start;
        len[n] = static_cast<size_t>(p - start);
      }
      n++;
    }
    if (n == 0) { w.text("ERR EMPTY"); return; }
    if (len[0] != 1) { w.text("ERR UNKNOWN"); return; }
    const char cmd = tok[0][0];
    int arity;
    switch (cmd) {
      case 'J': arity = 6; break;
      case 'W': arity = 2; break;
      case 'C': case 'N': arity = 1; break;
      case 'E': case 'R': case 'S': case 'H': case 'Z': case 'X': arity = 0; break;
      default: w.text("ERR UNKNOWN"); return;
    }
    if (n - 1 != arity) { w.text("ERR ARGS"); return; }

    switch (cmd) {
      case 'J': {
        double v[JOINTS];
        for (int i = 0; i < JOINTS; i++) {
          if (!number(tok[i + 1], len[i + 1], &v[i]) || v[i] > 1000.0 || v[i] < -1000.0) { w.text("ERR ARGS"); return; }
        }
        if (mode_ == RELAX) { w.text("ERR DISABLED"); return; }
        if (mode_ == CAL) { w.text("ERR CAL"); return; }
        int clamped = 0;
        double c[JOINTS];
        for (int i = 0; i < JOINTS; i++) {
          c[i] = bound(v[i], table_.joints[i].min_deg, table_.joints[i].max_deg);
          if (c[i] != v[i]) clamped++;
        }
        if (!clearance::legsClear(table_.legs, c)) { w.text("ERR CLEAR"); return; }
        for (int i = 0; i < JOINTS; i++) target_[i] = c[i];
        mode_ = RUN;
        armed_ = true;
        last_cmd_ms_ = now_ms;
        w.text("OK");
        if (clamped) { w.text(" CLAMP "); w.integer(clamped); }
        return;
      }
      case 'E':
        if (mode_ == RELAX) {
          for (int i = 0; i < JOINTS; i++) target_[i] = current_[i];
          mode_ = RUN;
          armed_ = false;
        }
        w.text("OK");
        return;
      case 'R':
        mode_ = RELAX;
        armed_ = false;
        cal_index_ = -1;
        w.text("OK");
        return;
      case 'H':
        // One line that stops the motion: the target becomes the commanded
        // angles of this instant, so no tick can move a joint afterwards.
        if (mode_ == RUN) {
          for (int i = 0; i < JOINTS; i++) target_[i] = current_[i];
          mode_ = HOLD;
          armed_ = false;
        }
        w.text("OK");
        return;
      case 'S':
        w.text("STAT mode=");
        w.text(mode_ == RELAX ? "RELAX" : mode_ == RUN ? "RUN" : mode_ == HOLD ? "HOLD" : "CAL");
        w.text(" age_ms=");
        w.integer(static_cast<uint32_t>(now_ms - last_cmd_ms_));
        w.text(" wd=");
        w.integer(watchdog_ms_);
        w.text(" q=");
        for (int i = 0; i < JOINTS; i++) {
          if (i) w.text(",");
          w.tenths(current_[i]);
        }
        return;
      case 'W': {
        uint32_t ms = 0;
        const bool hold = same(tok[2], len[2], "hold");
        const bool relax = same(tok[2], len[2], "relax");
        if (!digits(tok[1], len[1], &ms) || len[1] > 6 || !(hold || relax) || ms < 100 || ms > 10000) {
          w.text("ERR ARGS");
          return;
        }
        watchdog_ms_ = ms;
        watchdog_relax_ = relax;
        w.text("OK");
        return;
      }
      case 'C':
        if (len[1] != 1 || tok[1][0] < '0' || tok[1][0] > '5') { w.text("ERR ARGS"); return; }
        if (mode_ == RELAX) { w.text("ERR DISABLED"); return; }
        for (int i = 0; i < JOINTS; i++) target_[i] = current_[i];
        mode_ = CAL;
        armed_ = false;
        cal_index_ = tok[1][0] - '0';
        w.text("OK");
        return;
      case 'N': {
        double delta;
        if (!number(tok[1], len[1], &delta)) { w.text("ERR ARGS"); return; }
        if (mode_ != CAL) { w.text("ERR NOT CAL"); return; }
        if (delta > table_.step_max_deg || delta < -table_.step_max_deg) { w.text("ERR STEP"); return; }
        const int i = cal_index_;
        const double servo = calServo(delta);
        double moved[JOINTS];
        for (int k = 0; k < JOINTS; k++) moved[k] = current_[k];
        moved[i] = (servo - zero_[i]) / table_.joints[i].direction;
        if (!clearance::legsClear(table_.legs, moved)) { w.text("ERR CLEAR"); return; }
        current_[i] = moved[i];
        target_[i] = current_[i];
        w.text("CAL ");
        w.integer(i);
        w.text(" servo=");
        w.tenths(servo);
        w.text(" pulse=");
        w.integer(pulseFor(servo));
        return;
      }
      case 'Z': {
        if (mode_ != CAL) { w.text("ERR NOT CAL"); return; }
        const int i = cal_index_;
        const double servo = calServo(0.0);
        zero_[i] = servo;
        current_[i] = target_[i] = 0.0;
        w.text("ZERO ");
        w.integer(i);
        w.text(" ");
        w.tenths(servo);
        return;
      }
      case 'X':
        if (mode_ == CAL) {
          mode_ = HOLD;
          cal_index_ = -1;
        }
        w.text("OK");
        return;
    }
  }

 private:
  // Bounded text writer; avoids printf so no float formatting support is needed.
  class Writer {
   public:
    Writer(char *out, size_t size) : out_(out), size_(size) {
      if (size_) out_[0] = 0;
    }
    void text(const char *s) {
      while (*s && used_ + 1 < size_) out_[used_++] = *s++;
      if (size_) out_[used_] = 0;
    }
    void integer(uint32_t v) {
      char buf[12];
      int n = 0;
      do {
        buf[n++] = static_cast<char>('0' + v % 10);
        v /= 10;
      } while (v && n < 11);
      char rev[12];
      for (int i = 0; i < n; i++) rev[i] = buf[n - 1 - i];
      rev[n] = 0;
      text(rev);
    }
    // One decimal, half away from zero, no negative zero.
    void tenths(double v) {
      const double a = v < 0 ? -v : v;
      const uint32_t t = static_cast<uint32_t>(a * 10.0 + 0.5);
      if (v < 0 && t) text("-");
      integer(t / 10);
      text(".");
      integer(t % 10);
    }

   private:
    char *out_;
    size_t size_;
    size_t used_ = 0;
  };

  static double bound(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }

  int pulseFor(double servo_deg) const {
    const double b = bound(servo_deg, 0.0, 180.0);
    return static_cast<int>(table_.min_us + b * (table_.max_us - table_.min_us) / 180.0 + 0.5);
  }

  double calServo(double delta) const {
    const int i = cal_index_;
    return bound(zero_[i] + table_.joints[i].direction * current_[i] + delta, 0.0, 180.0);
  }

  static bool same(const char *s, size_t n, const char *word) {
    size_t i = 0;
    for (; i < n && word[i]; i++) {
      if (s[i] != word[i]) return false;
    }
    return i == n && word[i] == 0;
  }

  static bool digits(const char *s, size_t n, uint32_t *out) {
    if (n == 0 || n > 9) return false;
    uint32_t v = 0;
    for (size_t i = 0; i < n; i++) {
      if (s[i] < '0' || s[i] > '9') return false;
      v = v * 10 + static_cast<uint32_t>(s[i] - '0');
    }
    *out = v;
    return true;
  }

  // Strict decimal: optional sign, 1 to 6 digits, optional point and up to 6
  // digits. No exponent, no inf, no nan.
  static bool number(const char *s, size_t n, double *out) {
    size_t i = 0;
    bool negative = false;
    if (i < n && (s[i] == '-' || s[i] == '+')) {
      negative = s[i] == '-';
      i++;
    }
    uint32_t whole = 0;
    size_t whole_digits = 0;
    while (i < n && s[i] >= '0' && s[i] <= '9') {
      whole = whole * 10 + static_cast<uint32_t>(s[i] - '0');
      whole_digits++;
      i++;
    }
    if (whole_digits == 0 || whole_digits > 6) return false;
    uint32_t frac = 0;
    uint32_t scale = 1;
    if (i < n && s[i] == '.') {
      i++;
      size_t frac_digits = 0;
      while (i < n && s[i] >= '0' && s[i] <= '9') {
        frac = frac * 10 + static_cast<uint32_t>(s[i] - '0');
        scale *= 10;
        frac_digits++;
        i++;
      }
      if (frac_digits > 6) return false;
    }
    if (i != n) return false;
    // (whole * scale + frac) is exact in a double; one correctly rounded division.
    const double v = (static_cast<double>(whole) * scale + frac) / scale;
    *out = negative ? -v : v;
    return true;
  }

  const Table &table_;
  Mode mode_ = RELAX;
  double current_[JOINTS];
  double target_[JOINTS];
  double zero_[JOINTS];
  uint32_t last_cmd_ms_ = 0;
  uint32_t watchdog_ms_ = 500;
  bool watchdog_relax_ = false;
  bool armed_ = false;
  int cal_index_ = -1;
};

}  // namespace duck
