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
// Calibration: C/N/Z/X move one joint by steps of at most step_max_deg.
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
};

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
    for (int i = 0; i < JOINTS; i++) {
      current_[i] += bound(target_[i] - current_[i], -step, step);
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
      case 'E': case 'R': case 'S': case 'Z': case 'X': arity = 0; break;
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
        for (int i = 0; i < JOINTS; i++) {
          const double c = bound(v[i], table_.joints[i].min_deg, table_.joints[i].max_deg);
          if (c != v[i]) clamped++;
          target_[i] = c;
        }
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
        current_[i] = (servo - zero_[i]) / table_.joints[i].direction;
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
