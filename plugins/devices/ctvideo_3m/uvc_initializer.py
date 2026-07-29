"""CTvideo UVC defaults applied through an opened OpenCV DirectShow device."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class UVCControl:
    name: str
    entity: int
    selector: int
    value: int | bytes
    opencv_property: str | None = None


class UVCInitializer:
    """Apply the CTvideo UVC initialization profile before frame capture.

    Entity and selector values remain explicit so a native IKsControl backend
    can replace the OpenCV transport without changing the profile.
    """

    CONTROLS = (
        UVCControl("Brightness", 0x02, 0x02, -12, "CAP_PROP_BRIGHTNESS"),
        UVCControl("Contrast", 0x02, 0x03, 25, "CAP_PROP_CONTRAST"),
        UVCControl("Gain", 0x02, 0x04, 4, "CAP_PROP_GAIN"),
        UVCControl("Power Line", 0x02, 0x05, 2),
        UVCControl("Hue", 0x02, 0x06, 0, "CAP_PROP_HUE"),
        UVCControl("Saturation", 0x02, 0x07, 64, "CAP_PROP_SATURATION"),
        UVCControl("Sharpness", 0x02, 0x08, 0, "CAP_PROP_SHARPNESS"),
        UVCControl("Gamma", 0x02, 0x09, 100, "CAP_PROP_GAMMA"),
        UVCControl("Auto Exposure Mode", 0x01, 0x02, 1, "CAP_PROP_AUTO_EXPOSURE"),
        UVCControl("Exposure Absolute", 0x01, 0x04, 312, "CAP_PROP_EXPOSURE"),
        UVCControl("Auto Exposure Priority", 0x01, 0x03, 1),
        UVCControl("ROI", 0x01, 0x14, bytes(10)),
    )

    def __init__(self, cv2_module):
        self.cv2 = cv2_module

    @staticmethod
    def _transport_value(control):
        if control.name == "Auto Exposure Mode":
            # UVC: 1=manual, 2=auto. OpenCV DShow: 0.25=manual, 0.75=auto.
            return 0.25 if control.value == 1 else 0.75
        if control.name == "Exposure Absolute":
            # UVC unit is 100 us; OpenCV DShow exposure is log2(seconds).
            seconds = int(control.value) / 10_000.0
            return round(math.log2(seconds))
        return control.value

    def apply(self, capture, values=None):
        values = values or {}
        results = []
        for control in self.CONTROLS:
            value = values.get(control.name, control.value)
            control = UVCControl(
                control.name, control.entity, control.selector, value,
                control.opencv_property,
            )
            if control.name == "ROI" and not any(control.value):
                results.append(self._result(control, False, "ROI bytes not configured"))
                continue
            if control.opencv_property is None:
                results.append(self._result(control, False, "no OpenCV transport"))
                continue
            property_id = getattr(self.cv2, control.opencv_property, None)
            if property_id is None:
                results.append(self._result(control, False, "property unavailable"))
                continue
            requested = self._transport_value(control)
            accepted = bool(capture.set(property_id, requested))
            actual = capture.get(property_id)
            detail = f"requested={requested:g}, readback={actual:g}"
            results.append(self._result(control, accepted, detail))
        return results

    @staticmethod
    def _result(control, applied, detail):
        return {
            "name": control.name,
            "entity": control.entity,
            "selector": control.selector,
            "value": control.value,
            "applied": applied,
            "detail": detail,
        }
