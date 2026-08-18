"""Video display and persistent camera-control behavior for CTvideo 3M."""

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QCheckBox, QColorDialog, QMessageBox, QPushButton

from .video_display import CompactConnectVideoDisplaySettings


class CTVideoControlsMixin:
    """Own software display controls and confirmed camera EEPROM actions."""

    def _make_color_button(self, title, color):
        button = QPushButton()
        button.clicked.connect(
            lambda _checked=False, item=button, name=title:
            self._choose_video_color(item, name)
        )
        self._set_color_button(button, color)
        return button

    @staticmethod
    def _set_color_button(button, color):
        parsed = QColor(color)
        if not parsed.isValid():
            raise ValueError(f"Invalid color: {color}")
        canonical = parsed.name(QColor.NameFormat.HexRgb).upper()
        button.setProperty("video_color", canonical)
        button.setText(canonical)
        text_color = "#000000" if parsed.lightness() > 150 else "#FFFFFF"
        button.setStyleSheet(
            f"background:{canonical}; color:{text_color}; font-weight:600;"
        )

    def _choose_video_color(self, button, title):
        current = QColor(button.property("video_color") or "#000000")
        selected = QColorDialog.getColor(current, self, title)
        if selected.isValid():
            self._set_color_button(button, selected.name())
            self._video_display_changed()

    def _video_display_changed(self, _value=None):
        if self.video_view.worker is not None:
            self.apply_video_display_settings(log_change=False)

    def video_display_settings(self):
        return CompactConnectVideoDisplaySettings(
            red_gain=self.video_red_gain.value(),
            green_gain=self.video_green_gain.value(),
            blue_gain=self.video_blue_gain.value(),
            brightness=self.video_brightness.value(),
            rotation_deg=self.video_rotation.value(),
            black_and_white=self.video_black_white.isChecked(),
            mirror_x=self.video_mirror_x.isChecked(),
            mirror_y=self.video_mirror_y.isChecked(),
            target_circle_style=self.target_circle_style.currentData(),
            target_circle_width=self.target_circle_width.value(),
            target_circle_color=(
                self.target_circle_color.property("video_color")
            ),
            background_color=(
                self.video_background_color.property("video_color")
            ),
            background_circle_color=(
                self.background_circle_color.property("video_color")
            ),
            background_circle_diameter=(
                self.background_circle_diameter.value()
            ),
        ).to_dict()

    def _set_video_display_controls(self, settings):
        values = CompactConnectVideoDisplaySettings.from_mapping(settings)
        controls = (
            (self.video_red_gain, values.red_gain),
            (self.video_green_gain, values.green_gain),
            (self.video_blue_gain, values.blue_gain),
            (self.video_brightness, values.brightness),
            (self.video_rotation, values.rotation_deg),
            (self.video_black_white, values.black_and_white),
            (self.video_mirror_x, values.mirror_x),
            (self.video_mirror_y, values.mirror_y),
            (self.target_circle_width, values.target_circle_width),
            (
                self.background_circle_diameter,
                values.background_circle_diameter,
            ),
        )
        for control, value in controls:
            blocked = control.blockSignals(True)
            try:
                if isinstance(control, QCheckBox):
                    control.setChecked(bool(value))
                else:
                    control.setValue(value)
            finally:
                control.blockSignals(blocked)
        blocked = self.target_circle_style.blockSignals(True)
        try:
            index = self.target_circle_style.findData(values.target_circle_style)
            self.target_circle_style.setCurrentIndex(index)
        finally:
            self.target_circle_style.blockSignals(blocked)
        self._set_color_button(
            self.target_circle_color, values.target_circle_color
        )
        self._set_color_button(
            self.video_background_color, values.background_color
        )
        self._set_color_button(
            self.background_circle_color, values.background_circle_color
        )

    def reset_video_display_settings(self):
        self._set_video_display_controls(
            CompactConnectVideoDisplaySettings().to_dict()
        )
        self.apply_video_display_settings()

    def apply_video_display_settings(
        self, _checked=False, *, log_change=True
    ):
        try:
            settings = self.video_display_settings()
        except Exception as error:
            self.show_error(error)
            return False
        if not self.video_view.set_video_display_settings(settings):
            if log_change:
                self.log("Display apply skipped: video is not running")
            return False
        self.camera_status_label.setText(
            "Software video display settings applied"
        )
        if log_change:
            self.log("CompactConnect video display settings applied")
        return True

    def update_camera_properties(self, properties):
        controls = properties.get("controls") or {}
        operation = properties.get("operation", "read")
        if not controls:
            self.camera_status_label.setText(
                "CompactConnect camera hardware response is invalid"
            )
            return

        gain = controls.get("CompactConnect Video Gain")
        if gain is not None:
            supported = bool(gain.get("supported"))
            current = gain.get("current")
            applied = gain.get("applied")
            self.compactconnect_video_gain_supported = supported
            self.compactconnect_video_gain.setEnabled(
                supported and self.video_view.worker is not None
            )
            if current is not None:
                blocked = self.compactconnect_video_gain.blockSignals(True)
                try:
                    self.compactconnect_video_gain.setValue(int(current))
                finally:
                    self.compactconnect_video_gain.blockSignals(blocked)
            if not supported:
                text = "Unavailable"
            elif applied is True:
                text = f"Written and verified: {current}"
            elif applied is False:
                text = "Write failed"
            else:
                text = f"Current: {current}"
            detail = gain.get("detail") or text
            self.video_gain_readback.setText(text)
            self.video_gain_readback.setToolTip(detail)
            self.compactconnect_video_gain.setToolTip(detail)

        anti = controls.get("CompactConnect Anti-flicker")
        if anti is not None:
            supported = bool(anti.get("supported"))
            current = anti.get("current")
            applied = anti.get("applied")
            self.compactconnect_anti_flicker_supported = supported
            self.compactconnect_anti_flicker.setEnabled(
                supported and self.video_view.worker is not None
            )
            if current is not None:
                blocked = self.compactconnect_anti_flicker.blockSignals(True)
                try:
                    index = self.compactconnect_anti_flicker.findData(int(current))
                    if index >= 0:
                        self.compactconnect_anti_flicker.setCurrentIndex(index)
                finally:
                    self.compactconnect_anti_flicker.blockSignals(blocked)
            display = anti.get("display")
            if not supported:
                text = "Unavailable"
            elif applied is True:
                text = f"Written and verified: {display or current}"
            elif applied is False:
                text = "Write failed"
            else:
                text = f"Current: {display or current}"
            detail = anti.get("detail") or text
            self.anti_flicker_readback.setText(text)
            self.anti_flicker_readback.setToolTip(detail)
            self.compactconnect_anti_flicker.setToolTip(detail)

        worker_running = self.video_view.worker is not None
        self.write_video_gain_button.setEnabled(
            worker_running and self.compactconnect_video_gain_supported
        )
        self.write_anti_flicker_button.setEnabled(
            worker_running and self.compactconnect_anti_flicker_supported
        )

        if operation == "video_gain_apply":
            result = gain or {}
            message = (
                "CompactConnect Video Gain EEPROM write verified: "
                f"{result.get('current')}"
                if result.get("applied") is True else
                result.get("detail") or
                "CompactConnect Video Gain write failed"
            )
            self.camera_status_label.setText(message)
            self.log(message)
        elif operation == "anti_flicker_apply":
            result = anti or {}
            message = (
                "CompactConnect Anti-flicker EEPROM write verified: "
                f"{result.get('display') or result.get('current')}"
                if result.get("applied") is True else
                result.get("detail") or
                "CompactConnect Anti-flicker write failed"
            )
            self.camera_status_label.setText(message)
            self.log(message)
        else:
            available = sum(
                bool(result.get("supported")) for result in controls.values()
            )
            self.camera_status_label.setText(
                "CompactConnect camera hardware read: "
                f"{available}/{len(controls)} available"
            )

    def read_camera_hardware_settings(self):
        if not self.video_view.request_camera_properties():
            self.log("Camera hardware read skipped: video is not running")
            return False
        self.camera_status_label.setText(
            "Reading CompactConnect camera hardware..."
        )
        return True

    def apply_compactconnect_video_gain(self):
        if self.video_view.worker is None:
            self.log("Video gain write skipped: video is not running")
            return False
        if not self.compactconnect_video_gain_supported:
            self.log("Video gain write skipped: vendor YTarget is unavailable")
            return False
        value = self.compactconnect_video_gain.value()
        answer = QMessageBox.warning(
            self,
            "Write Persistent Camera Gain",
            "This writes CompactConnect Video Gain (YTarget) to the camera's "
            "persistent EEPROM. CompactConnect also updates related tuning "
            "bytes during this operation.\n\n"
            f"Write value {value}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.log("CompactConnect Video Gain write cancelled")
            return False
        if not self.video_view.set_compactconnect_video_gain(
            value, confirmed=True
        ):
            self.log("Video gain write skipped: video is not running")
            return False
        self.write_video_gain_button.setEnabled(False)
        self.camera_status_label.setText(
            f"Writing CompactConnect Video Gain {value}; awaiting read-back..."
        )
        self.log(
            f"CompactConnect Video Gain {value} queued after EEPROM confirmation"
        )
        return True

    def apply_compactconnect_anti_flicker(self):
        if self.video_view.worker is None:
            self.log("Anti-flicker write skipped: video is not running")
            return False
        if not self.compactconnect_anti_flicker_supported:
            self.log("Anti-flicker write skipped: vendor control is unavailable")
            return False
        mode = int(self.compactconnect_anti_flicker.currentData())
        label = self.compactconnect_anti_flicker.currentText()
        answer = QMessageBox.warning(
            self,
            "Write Persistent Anti-flicker",
            "This writes the CompactConnect Anti-flicker value to persistent "
            "camera EEPROM. Off and 50 Hz both use raw value 25, so those two "
            "states cannot be distinguished by read-back.\n\n"
            f"Write {label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.log("CompactConnect Anti-flicker write cancelled")
            return False
        if not self.video_view.set_compactconnect_anti_flicker(
            mode, confirmed=True
        ):
            self.log("Anti-flicker write skipped: video is not running")
            return False
        self.write_anti_flicker_button.setEnabled(False)
        self.camera_status_label.setText(
            f"Writing CompactConnect Anti-flicker {label}; awaiting read-back..."
        )
        self.log(
            f"CompactConnect Anti-flicker {label} queued after EEPROM confirmation"
        )
        return True
