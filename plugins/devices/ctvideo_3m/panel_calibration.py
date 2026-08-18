"""Calibration UI behavior for the CTvideo 3M settings panel."""

from PyQt6.QtWidgets import QMessageBox

from gui.widget_busy_spinner import run_busy_task

from .driver import CTVideo3M


class CTVideoCalibrationMixin:
    """Keep hazardous calibration reads and writes isolated from panel layout."""

    @staticmethod
    def _format_tweak_offset(value):
        return f"{value:.1f} °C"

    @staticmethod
    def _format_tweak_gain(value):
        return f"{value:.8f}"

    def _set_calibration_proposed_values(self, offset, gain):
        for control, value in (
            (self.calibration_offset_proposed, offset),
            (self.calibration_gain_proposed, gain),
        ):
            blocked = control.blockSignals(True)
            try:
                control.setValue(value)
            finally:
                control.blockSignals(blocked)

    def _show_calibration_snapshot(self, snapshot, *, populate_proposed):
        self.calibration_serial_label.setText(str(snapshot.serial_number))
        self.calibration_firmware_label.setText(str(snapshot.firmware_revision))
        self.calibration_offset_current.setText(
            f"{self._format_tweak_offset(snapshot.tweak_offset_C)} "
            f"(raw 0x{snapshot.raw_offset:04X})"
        )
        self.calibration_gain_current.setText(
            f"{self._format_tweak_gain(snapshot.tweak_gain)} "
            f"(raw 0x{snapshot.raw_gain:04X})"
        )
        if populate_proposed:
            self._set_calibration_proposed_values(
                snapshot.tweak_offset_C, snapshot.tweak_gain
            )

    def _collect_calibration_proposal(self):
        offset_raw = CTVideo3M.encode_tweak_offset(
            self.calibration_offset_proposed.value()
        )
        gain_raw = CTVideo3M.encode_tweak_gain(
            self.calibration_gain_proposed.value()
        )
        return {
            "tweak_offset_C": CTVideo3M.decode_tweak_offset(offset_raw),
            "tweak_gain": CTVideo3M.decode_tweak_gain(gain_raw),
        }, {
            "tweak_offset_C": offset_raw,
            "tweak_gain": gain_raw,
        }

    def _calibration_changes(self):
        snapshot = self.calibration_snapshot
        if snapshot is None:
            return {}, {}
        proposed, raw = self._collect_calibration_proposal()
        current_raw = {
            "tweak_offset_C": snapshot.raw_offset,
            "tweak_gain": snapshot.raw_gain,
        }
        changes = {
            key: proposed[key] for key in proposed if raw[key] != current_raw[key]
        }
        return changes, raw

    def _calibration_proposal_changed(self, _value=None):
        snapshot = self.calibration_snapshot
        if snapshot is None:
            self._update_calibration_actions()
            return
        try:
            changes, raw = self._calibration_changes()
            self.calibration_offset_readback.setText(
                f"Pending raw 0x{raw['tweak_offset_C']:04X}"
                if "tweak_offset_C" in changes else "Unchanged"
            )
            self.calibration_gain_readback.setText(
                f"Pending raw 0x{raw['tweak_gain']:04X}"
                if "tweak_gain" in changes else "Unchanged"
            )
            self.calibration_status_label.setText(
                "Review the change and acknowledge the warning before writing."
                if changes else
                "Proposed values match the current device calibration."
            )
        except Exception as error:
            self.calibration_status_label.setText(
                f"Invalid calibration value: {error}"
            )
        self._update_calibration_actions()

    def _update_calibration_actions(self, _checked=None):
        if not hasattr(self, "read_calibration_button"):
            return
        connected = self.get_device() is not None
        fresh = self.calibration_snapshot is not None
        try:
            dirty = bool(self._calibration_changes()[0]) if fresh else False
        except Exception:
            dirty = False
        enabled = not self._calibration_busy
        self.read_calibration_button.setEnabled(connected and enabled)
        self.calibration_offset_proposed.setEnabled(fresh and enabled)
        self.calibration_gain_proposed.setEnabled(fresh and enabled)
        self.calibration_ack.setEnabled(fresh and enabled)
        self.apply_calibration_button.setEnabled(
            connected and fresh and dirty and self.calibration_ack.isChecked()
            and enabled
        )

    def _invalidate_calibration_snapshot(self, reason):
        self.calibration_snapshot = None
        if not hasattr(self, "calibration_status_label"):
            return
        self.calibration_serial_label.setText("-")
        self.calibration_firmware_label.setText("-")
        self.calibration_offset_current.setText("-")
        self.calibration_gain_current.setText("-")
        self.calibration_offset_readback.setText(
            "Read current calibration first"
        )
        self.calibration_gain_readback.setText("Read current calibration first")
        self.calibration_ack.setChecked(False)
        self.calibration_status_label.setText(reason)
        self._update_calibration_actions()

    def read_calibration(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the pyrometer first.")
            return False
        self._calibration_busy = True
        self.calibration_status_label.setText(
            "Reading calibration and device identity..."
        )
        self._update_calibration_actions()

        def completed(snapshot):
            self.calibration_snapshot = snapshot
            self._show_calibration_snapshot(snapshot, populate_proposed=True)
            self.calibration_offset_readback.setText(
                "Current value read from device"
            )
            self.calibration_gain_readback.setText(
                "Current value read from device"
            )
            self.calibration_ack.setChecked(False)
            self.calibration_status_label.setText(
                "Calibration read successfully. Edit only the proposed value "
                "column."
            )
            self.log(
                "Calibration read: serial "
                f"{snapshot.serial_number}, offset "
                f"{self._format_tweak_offset(snapshot.tweak_offset_C)}, gain "
                f"{self._format_tweak_gain(snapshot.tweak_gain)}"
            )
            self._calibration_busy = False
            self._update_calibration_actions()

        def failed(error):
            self._invalidate_calibration_snapshot(
                "Calibration read failed; no calibration write is allowed."
            )
            self._calibration_busy = False
            self._update_calibration_actions()
            self.show_error(error)

        run_busy_task(
            self, device.read_calibration, completed, failed,
            key="device_action",
        )
        return True

    def apply_calibration(self):
        device = self.get_device()
        snapshot = self.calibration_snapshot
        if device is None:
            self.show_error("Connect the pyrometer first.")
            return False
        if snapshot is None:
            self.show_error("Read the current calibration before writing.")
            return False
        if not self.calibration_ack.isChecked():
            self.show_error(
                "Acknowledge the calibration warning before writing."
            )
            return False
        try:
            changes, _raw = self._calibration_changes()
            proposed, _ = self._collect_calibration_proposal()
        except Exception as error:
            self.show_error(error)
            return False
        if not changes:
            self.log("Calibration write skipped: proposed values are unchanged")
            self._update_calibration_actions()
            return False

        lines = [
            f"Device serial: {snapshot.serial_number}",
            "",
            "The following pyrometer calibration values will be written:",
        ]
        if "tweak_offset_C" in changes:
            lines.append(
                f"Tweak Offset: "
                f"{self._format_tweak_offset(snapshot.tweak_offset_C)} -> "
                f"{self._format_tweak_offset(proposed['tweak_offset_C'])}"
            )
        if "tweak_gain" in changes:
            lines.append(
                f"Tweak Gain: {self._format_tweak_gain(snapshot.tweak_gain)} -> "
                f"{self._format_tweak_gain(proposed['tweak_gain'])}"
            )
        lines.extend((
            "",
            "This immediately changes measured temperatures. Continue?",
        ))
        answer = QMessageBox.warning(
            self,
            "Write Pyrometer Calibration",
            "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.log("Calibration write cancelled")
            return False

        self._calibration_busy = True
        self.calibration_status_label.setText(
            "Checking the snapshot, writing once, and verifying read-back..."
        )
        self._update_calibration_actions()

        def completed(result):
            self._show_calibration_snapshot(
                result.after, populate_proposed=False
            )
            field_rows = (
                (
                    "tweak_offset_C", self.calibration_offset_readback,
                    self._format_tweak_offset(result.after.tweak_offset_C),
                    result.after.raw_offset,
                ),
                (
                    "tweak_gain", self.calibration_gain_readback,
                    self._format_tweak_gain(result.after.tweak_gain),
                    result.after.raw_gain,
                ),
            )
            for key, label, value, raw in field_rows:
                label.setText(
                    f"{result.statuses[key].replace('_', ' ').title()}: "
                    f"{value} (raw 0x{raw:04X})"
                )
            if result.verified:
                self.calibration_snapshot = result.after
                self._set_calibration_proposed_values(
                    result.after.tweak_offset_C, result.after.tweak_gain
                )
                self.calibration_ack.setChecked(False)
                self.calibration_status_label.setText(
                    "Calibration write verified against a fresh device read-back."
                )
                self.log(
                    "Calibration write verified: offset "
                    f"{self._format_tweak_offset(result.after.tweak_offset_C)}, "
                    f"gain {self._format_tweak_gain(result.after.tweak_gain)}"
                )
            else:
                self.calibration_snapshot = None
                self.calibration_ack.setChecked(False)
                self.calibration_status_label.setText(
                    "Calibration read-back mismatch. Read calibration again before "
                    "any further write."
                )
                self.log("Calibration write was not fully verified")
            self._calibration_busy = False
            self._update_calibration_actions()

        def failed(error):
            self._invalidate_calibration_snapshot(
                "Calibration write state is uncertain. Read calibration again "
                "before any further write."
            )
            self._calibration_busy = False
            self._update_calibration_actions()
            self.show_error(error)

        run_busy_task(
            self,
            lambda: device.apply_calibration(
                snapshot, proposed, confirmed=True
            ),
            completed,
            failed,
            key="device_action",
        )
        return True
