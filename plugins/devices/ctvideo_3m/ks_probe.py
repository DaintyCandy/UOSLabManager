"""Read-only DirectShow/Kernel Streaming probe for the CTvideo camera.

This module intentionally never sends KSPROPERTY_TYPE_SET.  It is a diagnostic
tool used to discover the KS node IDs and the controls exposed by usbvideo.sys.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from ctypes import wintypes

from .usb_camera import resolve_camera_for_port


HRESULT = ctypes.c_long
ULONG = wintypes.ULONG
DWORD = wintypes.DWORD

S_OK = 0
S_FALSE = 1
CLSCTX_INPROC_SERVER = 1
VFW_S_STATE_INTERMEDIATE = 0x00040237
KSPROPERTY_TYPE_GET = 0x00000001
KSPROPERTY_TYPE_BASICSUPPORT = 0x80000000
KSPROPERTY_TYPE_TOPOLOGY = 0x10000000


class GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def from_string(cls, value: str) -> "GUID":
        import uuid

        raw = uuid.UUID(value).bytes_le
        return cls.from_buffer_copy(raw)

    def __str__(self):
        raw = bytes(self)
        import uuid

        return str(uuid.UUID(bytes_le=raw))


class VARIANT_UNION(ctypes.Union):
    _fields_ = (
        ("llVal", ctypes.c_longlong),
        ("lVal", ctypes.c_long),
        ("bstrVal", ctypes.c_void_p),
        ("punkVal", ctypes.c_void_p),
    )


class VARIANT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = (
        ("vt", wintypes.USHORT),
        ("reserved1", wintypes.USHORT),
        ("reserved2", wintypes.USHORT),
        ("reserved3", wintypes.USHORT),
        ("value", VARIANT_UNION),
    )


class KSPROPERTY(ctypes.Structure):
    _fields_ = (("Set", GUID), ("Id", ULONG), ("Flags", ULONG))


class KSP_NODE(ctypes.Structure):
    _fields_ = (("Property", KSPROPERTY), ("NodeId", ULONG), ("Reserved", ULONG))


class KSPROPERTY_NODE_VALUE(ctypes.Structure):
    _fields_ = (
        ("NodeProperty", KSP_NODE),
        ("Value", ctypes.c_long),
        ("Flags", ULONG),
        ("Capabilities", ULONG),
    )


class KSPROPERTY_VALUE(ctypes.Structure):
    _fields_ = (
        ("Value", ctypes.c_long),
        ("Flags", ULONG),
        ("Capabilities", ULONG),
    )


class KSPROPERTY_FILTER_VALUE(ctypes.Structure):
    _fields_ = (
        ("Property", KSPROPERTY),
        ("Value", ctypes.c_long),
        ("Flags", ULONG),
        ("Capabilities", ULONG),
    )


CLSID_SYSTEM_DEVICE_ENUM = GUID.from_string("62be5d10-60eb-11d0-bd3b-00a0c911ce86")
IID_ICREATE_DEV_ENUM = GUID.from_string("29840822-5b84-11d0-bd3b-00a0c911ce86")
CLSID_VIDEO_INPUT_CATEGORY = GUID.from_string("860bb310-5d01-11d0-bd3b-00a0c911ce86")
IID_IBASE_FILTER = GUID.from_string("56a86895-0ad4-11ce-b03a-0020af0ba770")
IID_IPROPERTY_BAG = GUID.from_string("55272a00-42cb-11ce-8135-00aa004bb851")
IID_IKS_TOPOLOGY_INFO = GUID.from_string("720d4ac0-7533-11d0-a5d6-28db04c10000")
IID_IKS_CONTROL = GUID.from_string("28f54685-06fd-11d2-b27a-00a0c9223196")
CLSID_FILTER_GRAPH = GUID.from_string("e436ebb3-524f-11ce-9f53-0020af0ba770")
IID_IGRAPH_BUILDER = GUID.from_string("56a868a9-0ad4-11ce-b03a-0020af0ba770")
CLSID_CAPTURE_GRAPH_BUILDER2 = GUID.from_string("bf87b6e1-8c27-11d0-b3f0-00aa003761c5")
IID_ICAPTURE_GRAPH_BUILDER2 = GUID.from_string("93e5a4e0-2d50-11d2-abfa-00a0c9c6e38d")
CLSID_NULL_RENDERER = GUID.from_string("c1f400a4-3f08-11d3-9f0b-006008039e37")
IID_IMEDIA_CONTROL = GUID.from_string("56a868b1-0ad4-11ce-b03a-0020af0ba770")
PIN_CATEGORY_CAPTURE = GUID.from_string("fb6c4281-0353-11d1-905f-0000c0cc16ba")
MEDIATYPE_VIDEO = GUID.from_string("73646976-0000-0010-8000-00aa00389b71")

KSNODETYPE_VIDEO_PROCESSING = "dff229e5-f70f-11d0-b917-00a0c9223196"
KSNODETYPE_VIDEO_CAMERA_TERMINAL = "dff229e6-f70f-11d0-b917-00a0c9223196"

PROPSETID_VIDCAP_VIDEOPROCAMP = GUID.from_string("c6e13360-30ac-11d0-a18c-00a0c9118956")
PROPSETID_VIDCAP_CAMERACONTROL = GUID.from_string("c6e13370-30ac-11d0-a18c-00a0c9118956")

VIDEO_PROC_AMP = {
    0: "Brightness", 1: "Contrast", 2: "Hue", 3: "Saturation",
    4: "Sharpness", 5: "Gamma", 9: "Gain", 13: "Power Line Frequency",
}
CAMERA_CONTROL = {
    4: "Exposure", 19: "Auto Exposure Priority",
}


def _failed(hr: int) -> bool:
    return ctypes.c_long(hr).value < 0


def _hr_hex(hr: int) -> str:
    return f"0x{ctypes.c_ulong(hr).value:08X}"


def _method(pointer, index, restype, *argtypes):
    address = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[index]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(address)


def _release(pointer):
    if pointer:
        _method(pointer, 2, ULONG)(pointer)


def _query_interface(pointer, iid):
    result = ctypes.c_void_p()
    hr = _method(
        pointer, 0, HRESULT, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
    )(pointer, ctypes.byref(iid), ctypes.byref(result))
    return result if not _failed(hr) else None


def _create_instance(clsid, iid):
    result = ctypes.c_void_p()
    hr = ctypes.windll.ole32.CoCreateInstance(
        ctypes.byref(clsid), None, CLSCTX_INPROC_SERVER,
        ctypes.byref(iid), ctypes.byref(result),
    )
    if _failed(hr):
        raise OSError(f"CoCreateInstance failed: {_hr_hex(hr)}")
    return result


class _PausedCaptureGraph:
    """Connect a capture pin to a Null Renderer and pause the graph."""

    def __init__(self, source_filter):
        self.source_filter = source_filter
        self.graph = None
        self.capture_builder = None
        self.null_renderer = None
        self.media_control = None
        self.details = {}

    def __enter__(self):
        self.graph = _create_instance(CLSID_FILTER_GRAPH, IID_IGRAPH_BUILDER)
        self.capture_builder = _create_instance(
            CLSID_CAPTURE_GRAPH_BUILDER2, IID_ICAPTURE_GRAPH_BUILDER2
        )
        self.null_renderer = _create_instance(CLSID_NULL_RENDERER, IID_IBASE_FILTER)
        try:
            hr = _method(
                self.capture_builder, 3, HRESULT, ctypes.c_void_p
            )(self.capture_builder, self.graph)
            self.details["set_filter_graph_hr"] = _hr_hex(hr)
            if _failed(hr):
                raise OSError(f"SetFiltergraph failed: {_hr_hex(hr)}")

            add_filter = _method(
                self.graph, 3, HRESULT, ctypes.c_void_p, wintypes.LPCWSTR
            )
            hr = add_filter(self.graph, self.source_filter, "CTvideo Source")
            self.details["add_source_hr"] = _hr_hex(hr)
            if _failed(hr):
                raise OSError(f"AddFilter(camera) failed: {_hr_hex(hr)}")
            hr = add_filter(self.graph, self.null_renderer, "CTvideo Null Renderer")
            self.details["add_renderer_hr"] = _hr_hex(hr)
            if _failed(hr):
                raise OSError(f"AddFilter(Null Renderer) failed: {_hr_hex(hr)}")

            # ICaptureGraphBuilder2::RenderStream
            hr = _method(
                self.capture_builder, 7, HRESULT,
                ctypes.POINTER(GUID), ctypes.POINTER(GUID),
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            )(
                self.capture_builder, ctypes.byref(PIN_CATEGORY_CAPTURE),
                ctypes.byref(MEDIATYPE_VIDEO), self.source_filter, None,
                self.null_renderer,
            )
            self.details["render_stream_hr"] = _hr_hex(hr)
            if _failed(hr):
                raise OSError(f"RenderStream(capture) failed: {_hr_hex(hr)}")

            self.media_control = _query_interface(self.graph, IID_IMEDIA_CONTROL)
            if not self.media_control:
                raise RuntimeError("Filter graph does not expose IMediaControl.")
            # IMediaControl derives from IDispatch; Pause is vtable slot 8.
            hr = _method(self.media_control, 8, HRESULT)(self.media_control)
            self.details["pause_hr"] = _hr_hex(hr)
            if _failed(hr):
                raise OSError(f"IMediaControl::Pause failed: {_hr_hex(hr)}")
            self.details["state"] = (
                "paused-intermediate" if hr == VFW_S_STATE_INTERMEDIATE else "paused"
            )
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, _type, _value, _traceback):
        if self.media_control:
            # IMediaControl::Stop is vtable slot 9.
            _method(self.media_control, 9, HRESULT)(self.media_control)
        _release(self.media_control)
        _release(self.null_renderer)
        _release(self.capture_builder)
        _release(self.graph)
        self.media_control = self.null_renderer = self.capture_builder = self.graph = None


def _property_bag_text(moniker, name):
    bag = ctypes.c_void_p()
    # IMoniker::BindToStorage is vtable slot 9.
    hr = _method(
        moniker, 9, HRESULT, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
    )(moniker, None, None, ctypes.byref(IID_IPROPERTY_BAG), ctypes.byref(bag))
    if _failed(hr):
        return None
    value = VARIANT()
    try:
        # IPropertyBag::Read is vtable slot 3.
        hr = _method(
            bag, 3, HRESULT, wintypes.LPCWSTR, ctypes.POINTER(VARIANT), ctypes.c_void_p
        )(bag, name, ctypes.byref(value), None)
        if _failed(hr) or value.vt != 8 or not value.bstrVal:  # VT_BSTR
            return None
        return ctypes.wstring_at(value.bstrVal)
    finally:
        ctypes.windll.oleaut32.VariantClear(ctypes.byref(value))
        _release(bag)


def _enumerate_video_filters():
    dev_enum = ctypes.c_void_p()
    hr = ctypes.windll.ole32.CoCreateInstance(
        ctypes.byref(CLSID_SYSTEM_DEVICE_ENUM), None, CLSCTX_INPROC_SERVER,
        ctypes.byref(IID_ICREATE_DEV_ENUM), ctypes.byref(dev_enum),
    )
    if _failed(hr):
        raise OSError(f"CoCreateInstance(SystemDeviceEnum) failed: {_hr_hex(hr)}")
    enum_moniker = ctypes.c_void_p()
    try:
        hr = _method(
            dev_enum, 3, HRESULT, ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p), DWORD,
        )(dev_enum, ctypes.byref(CLSID_VIDEO_INPUT_CATEGORY), ctypes.byref(enum_moniker), 0)
        if hr == S_FALSE:
            return
        if _failed(hr):
            raise OSError(f"CreateClassEnumerator failed: {_hr_hex(hr)}")
        while True:
            moniker = ctypes.c_void_p()
            fetched = ULONG()
            hr = _method(
                enum_moniker, 3, HRESULT, ULONG, ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ULONG),
            )(enum_moniker, 1, ctypes.byref(moniker), ctypes.byref(fetched))
            if hr != S_OK or not fetched.value:
                break
            try:
                filter_pointer = ctypes.c_void_p()
                hr = _method(
                    moniker, 8, HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
                )(moniker, None, None, ctypes.byref(IID_IBASE_FILTER),
                  ctypes.byref(filter_pointer))
                if not _failed(hr):
                    yield {
                        "name": _property_bag_text(moniker, "FriendlyName") or "",
                        "device_path": _property_bag_text(moniker, "DevicePath") or "",
                        "filter": filter_pointer,
                    }
            finally:
                _release(moniker)
    finally:
        _release(enum_moniker)
        _release(dev_enum)


def enumerate_video_inputs() -> list[dict]:
    """Return DirectShow video inputs in the same order used by CAP_DSHOW."""
    if sys.platform != "win32":
        return []
    initialized = not _failed(ctypes.windll.ole32.CoInitializeEx(None, 0))
    try:
        devices = []
        for index, item in enumerate(_enumerate_video_filters()):
            try:
                devices.append({
                    "index": index,
                    "name": item["name"],
                    "device_path": item["device_path"],
                })
            finally:
                _release(item["filter"])
        return devices
    finally:
        if initialized:
            ctypes.windll.ole32.CoUninitialize()


def _ks_property(ks_control, node_id, property_set, property_id, request_type):
    request = KSPROPERTY_NODE_VALUE()
    request.NodeProperty.Property.Set = property_set
    request.NodeProperty.Property.Id = property_id
    request.NodeProperty.Property.Flags = request_type | KSPROPERTY_TYPE_TOPOLOGY
    request.NodeProperty.NodeId = node_id
    returned = ULONG()
    call = _method(
        ks_control, 3, HRESULT, ctypes.c_void_p, ULONG, ctypes.c_void_p,
        ULONG, ctypes.POINTER(ULONG),
    )
    if request_type == KSPROPERTY_TYPE_GET:
        # Node camera-control GETs use the complete node structure as a shared
        # in/out buffer.  Value, Flags and Capabilities are filled in-place.
        queried_size = 0
        size_hr = 0
        output_size = ctypes.sizeof(request)
        output = request
        output_pointer = ctypes.byref(output)
        property_size = ctypes.sizeof(request)
    else:
        # BASICSUPPORT returns a KSPROPERTY_DESCRIPTION, not a camera-control
        # value structure.  Query it using only the KSP_NODE descriptor.
        size_hr = call(
            ks_control, ctypes.byref(request), ctypes.sizeof(request.NodeProperty),
            None, 0, ctypes.byref(returned),
        )
        queried_size = returned.value
        output_size = max(queried_size, 1024)
        output = (ctypes.c_ubyte * output_size)()
        output_pointer = ctypes.byref(output)
        property_size = ctypes.sizeof(request.NodeProperty)
    returned = ULONG()
    hr = call(
        ks_control, ctypes.byref(request), property_size,
        output_pointer, output_size, ctypes.byref(returned),
    )
    result = {
        "hr": _hr_hex(hr), "ok": not _failed(hr), "bytes_returned": returned.value,
        "size_query_hr": _hr_hex(size_hr), "queried_bytes": queried_size,
        "buffer_bytes": output_size,
    }
    if not _failed(hr) and request_type == KSPROPERTY_TYPE_GET:
        result.update({
            "value": output.Value,
            "flags": f"0x{output.Flags:08X}",
            "capabilities": f"0x{output.Capabilities:08X}",
        })
    elif not _failed(hr):
        result["raw_hex"] = bytes(output[:returned.value]).hex(" ")
    return result


def _ks_filter_property(ks_control, property_set, property_id, request_type):
    """Probe the filter-target form used by some usbvideo.sys devices."""
    request = KSPROPERTY_FILTER_VALUE()
    request.Property.Set = property_set
    request.Property.Id = property_id
    request.Property.Flags = request_type
    returned = ULONG()
    call = _method(
        ks_control, 3, HRESULT, ctypes.c_void_p, ULONG, ctypes.c_void_p,
        ULONG, ctypes.POINTER(ULONG),
    )
    if request_type == KSPROPERTY_TYPE_GET:
        size_hr = 0
        queried_size = 0
        output = request
        output_size = ctypes.sizeof(output)
        output_pointer = ctypes.byref(output)
        property_size = ctypes.sizeof(request)
    else:
        size_hr = call(
            ks_control, ctypes.byref(request.Property), ctypes.sizeof(request.Property),
            None, 0, ctypes.byref(returned),
        )
        queried_size = returned.value
        output_size = max(queried_size, 1024)
        output = (ctypes.c_ubyte * output_size)()
        output_pointer = ctypes.byref(output)
        property_size = ctypes.sizeof(request.Property)
    returned = ULONG()
    hr = call(
        ks_control, ctypes.byref(request), property_size,
        output_pointer, output_size, ctypes.byref(returned),
    )
    result = {
        "hr": _hr_hex(hr), "ok": not _failed(hr), "bytes_returned": returned.value,
        "size_query_hr": _hr_hex(size_hr), "queried_bytes": queried_size,
        "buffer_bytes": output_size,
    }
    if not _failed(hr) and request_type == KSPROPERTY_TYPE_GET:
        result.update({
            "value": output.Value,
            "flags": f"0x{output.Flags:08X}",
            "capabilities": f"0x{output.Capabilities:08X}",
        })
    elif not _failed(hr):
        result["raw_hex"] = bytes(output[:returned.value]).hex(" ")
    return result


def _probe_filter(filter_pointer):
    topology = _query_interface(filter_pointer, IID_IKS_TOPOLOGY_INFO)
    ks_control = _query_interface(filter_pointer, IID_IKS_CONTROL)
    if not topology:
        raise RuntimeError("Capture filter does not expose IKsTopologyInfo.")
    if not ks_control:
        _release(topology)
        raise RuntimeError("Capture filter does not expose IKsControl.")
    try:
        count = DWORD()
        hr = _method(topology, 8, HRESULT, ctypes.POINTER(DWORD))(
            topology, ctypes.byref(count)
        )
        if _failed(hr):
            raise OSError(f"IKsTopologyInfo::get_NumNodes failed: {_hr_hex(hr)}")
        nodes = []
        for node_id in range(count.value):
            node_type = GUID()
            hr = _method(
                topology, 9, HRESULT, DWORD, ctypes.POINTER(GUID)
            )(topology, node_id, ctypes.byref(node_type))
            node = {"id": node_id, "type": str(node_type), "type_name": "Other"}
            if _failed(hr):
                node["error"] = _hr_hex(hr)
                nodes.append(node)
                continue
            property_set = None
            properties = {}
            if node["type"] == KSNODETYPE_VIDEO_PROCESSING:
                node["type_name"] = "Video Processing"
                property_set, properties = PROPSETID_VIDCAP_VIDEOPROCAMP, VIDEO_PROC_AMP
            elif node["type"] == KSNODETYPE_VIDEO_CAMERA_TERMINAL:
                node["type_name"] = "Video Camera Terminal"
                property_set, properties = PROPSETID_VIDCAP_CAMERACONTROL, CAMERA_CONTROL
            if property_set:
                node["properties"] = []
                node_control = ctypes.c_void_p()
                create_hr = _method(
                    topology, 10, HRESULT, DWORD, ctypes.POINTER(GUID),
                    ctypes.POINTER(ctypes.c_void_p),
                )(topology, node_id, ctypes.byref(IID_IKS_CONTROL),
                  ctypes.byref(node_control))
                node["create_node_hr"] = _hr_hex(create_hr)
                if not _failed(create_hr):
                    try:
                        for property_id, name in properties.items():
                            node["properties"].append({
                                "id": property_id,
                                "name": name,
                                "node_basic_support": _ks_property(
                                    ks_control, node_id, property_set, property_id,
                                    KSPROPERTY_TYPE_BASICSUPPORT,
                                ),
                                "node_current": _ks_property(
                                    ks_control, node_id, property_set, property_id,
                                    KSPROPERTY_TYPE_GET,
                                ),
                                "filter_basic_support": _ks_filter_property(
                                    ks_control, property_set, property_id,
                                    KSPROPERTY_TYPE_BASICSUPPORT,
                                ),
                                "filter_current": _ks_filter_property(
                                    ks_control, property_set, property_id,
                                    KSPROPERTY_TYPE_GET,
                                ),
                            })
                    finally:
                        _release(node_control)
            nodes.append(node)
        return nodes
    finally:
        _release(ks_control)
        _release(topology)


def probe_port(port: str) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("The IKsControl probe is available only on Windows.")
    camera = resolve_camera_for_port(port)
    target_name = camera["CameraName"].strip().casefold()
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    try:
        discovered = []
        selected = None
        for item in _enumerate_video_filters():
            discovered.append({"name": item["name"], "device_path": item["device_path"]})
            if selected is None and item["name"].strip().casefold() == target_name:
                selected = item
            else:
                _release(item["filter"])
        if selected is None:
            raise RuntimeError(
                f"DirectShow filter not found for {camera['CameraName']!r}; "
                f"found {[item['name'] for item in discovered]!r}"
            )
        try:
            with _PausedCaptureGraph(selected["filter"]) as capture_graph:
                nodes = _probe_filter(selected["filter"])
                graph_details = dict(capture_graph.details)
        finally:
            _release(selected["filter"])
        return {
            "read_only": True,
            "port": camera,
            "directshow_filter": {
                "name": selected["name"], "device_path": selected["device_path"],
            },
            "capture_graph": graph_details,
            "nodes": nodes,
            "enumerated_filters": discovered,
        }
    finally:
        ctypes.windll.ole32.CoUninitialize()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only CTvideo KS camera probe")
    parser.add_argument("--port", default="COM6", help="CTvideo serial port (default: COM6)")
    parser.add_argument("--output", help="Optional UTF-8 JSON output file")
    args = parser.parse_args(argv)
    result = probe_port(args.port)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
