/*
 * Interface-scoped UVC control helper for macOS.
 *
 * This deliberately opens only the USB VideoControl interface. It never
 * seizes, resets, or changes the configuration of the whole USB device, so it
 * can be used alongside AVFoundation capture.
 */

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/usb/IOUSBLib.h>
#include <libkern/OSByteOrder.h>

#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if MAC_OS_X_VERSION_MAX_ALLOWED < 120000
#define kIOMainPortDefault kIOMasterPortDefault
#endif

#define CS_INTERFACE 0x24
#define VC_HEADER 0x01
#define VC_INPUT_TERMINAL 0x02
#define VC_PROCESSING_UNIT 0x05

#define UVC_SET_CUR 0x01
#define UVC_GET_CUR 0x81
#define UVC_GET_MIN 0x82
#define UVC_GET_MAX 0x83
#define UVC_GET_RES 0x84
#define UVC_GET_INFO 0x86
#define UVC_GET_DEF 0x87

#define CTVIDEO_CAMERA_VENDOR_ID 0x093A
#define CTVIDEO_CAMERA_PRODUCT_ID 0x2900

typedef enum {
    UNIT_CAMERA_TERMINAL,
    UNIT_PROCESSING,
} UnitKind;

typedef struct {
    const char *key;
    const char *display_name;
    UnitKind unit_kind;
    uint8_t selector;
    uint8_t size;
    bool signed_value;
    uint8_t advertised_bit;
} ControlDefinition;

static const ControlDefinition CONTROLS[] = {
    {"brightness", "Brightness", UNIT_PROCESSING, 0x02, 2, true, 0},
    {"contrast", "Contrast", UNIT_PROCESSING, 0x03, 2, false, 1},
    {"gain", "Gain", UNIT_PROCESSING, 0x04, 2, false, 9},
    {"power-line", "Power Line", UNIT_PROCESSING, 0x05, 1, false, 10},
    {"hue", "Hue", UNIT_PROCESSING, 0x06, 2, true, 2},
    {"saturation", "Saturation", UNIT_PROCESSING, 0x07, 2, false, 3},
    {"sharpness", "Sharpness", UNIT_PROCESSING, 0x08, 2, false, 4},
    {"gamma", "Gamma", UNIT_PROCESSING, 0x09, 2, false, 5},
    {"auto-exposure-mode", "Auto Exposure Mode", UNIT_CAMERA_TERMINAL, 0x02, 1, false, 1},
    {"auto-exposure-priority", "Auto Exposure Priority", UNIT_CAMERA_TERMINAL, 0x03, 1, false, 2},
    {"exposure-absolute", "Exposure Absolute", UNIT_CAMERA_TERMINAL, 0x04, 4, false, 3},
};

typedef struct {
    IOUSBInterfaceInterface220 **interface;
    uint8_t interface_number;
    uint8_t camera_terminal_id;
    uint8_t processing_unit_id;
    uint8_t terminal_controls[8];
    size_t terminal_controls_size;
    uint8_t processing_controls[8];
    size_t processing_controls_size;
    bool opened_by_helper;
} UVCContext;

typedef struct {
    bool supported;
    bool settable;
    bool has_minimum;
    bool has_maximum;
    bool has_step;
    bool has_default;
    bool has_current;
    int64_t minimum;
    int64_t maximum;
    int64_t step;
    int64_t default_value;
    int64_t current;
} ControlState;

static uint16_t read_le16(const uint8_t *value) {
    uint16_t result;
    memcpy(&result, value, sizeof(result));
    return OSSwapLittleToHostInt16(result);
}

static int64_t decode_value(const uint8_t *data, uint8_t size, bool is_signed) {
    if (size == 1) {
        return is_signed ? (int64_t)(int8_t)data[0] : (int64_t)data[0];
    }
    if (size == 2) {
        uint16_t raw;
        memcpy(&raw, data, sizeof(raw));
        raw = OSSwapLittleToHostInt16(raw);
        return is_signed ? (int64_t)(int16_t)raw : (int64_t)raw;
    }
    if (size == 4) {
        uint32_t raw;
        memcpy(&raw, data, sizeof(raw));
        raw = OSSwapLittleToHostInt32(raw);
        return is_signed ? (int64_t)(int32_t)raw : (int64_t)raw;
    }
    return 0;
}

static void encode_value(uint8_t *data, uint8_t size, int64_t value) {
    memset(data, 0, 8);
    if (size == 1) {
        data[0] = (uint8_t)value;
    } else if (size == 2) {
        uint16_t raw = OSSwapHostToLittleInt16((uint16_t)value);
        memcpy(data, &raw, sizeof(raw));
    } else if (size == 4) {
        uint32_t raw = OSSwapHostToLittleInt32((uint32_t)value);
        memcpy(data, &raw, sizeof(raw));
    }
}

static bool advertised(const UVCContext *context, const ControlDefinition *control) {
    const uint8_t *bitmap;
    size_t size;
    if (control->unit_kind == UNIT_PROCESSING) {
        bitmap = context->processing_controls;
        size = context->processing_controls_size;
    } else {
        bitmap = context->terminal_controls;
        size = context->terminal_controls_size;
    }
    if (size == 0) {
        return true;
    }
    size_t byte_index = control->advertised_bit / 8;
    uint8_t bit_index = control->advertised_bit % 8;
    return byte_index < size && (bitmap[byte_index] & (1u << bit_index)) != 0;
}

static uint8_t unit_id(const UVCContext *context, const ControlDefinition *control) {
    return control->unit_kind == UNIT_PROCESSING
        ? context->processing_unit_id : context->camera_terminal_id;
}

static IOReturn request(
    UVCContext *context,
    const ControlDefinition *control,
    uint8_t request_code,
    uint8_t direction,
    void *data,
    uint16_t length
) {
    IOUSBDevRequestTO request_data = {
        .bmRequestType = USBmakebmRequestType(direction, kUSBClass, kUSBInterface),
        .bRequest = request_code,
        .wValue = (uint16_t)(control->selector << 8),
        .wIndex = (uint16_t)((unit_id(context, control) << 8) | context->interface_number),
        .wLength = length,
        .pData = data,
        .wLenDone = 0,
        .noDataTimeout = 1000,
        .completionTimeout = 1000,
    };
    return (*context->interface)->ControlRequestTO(context->interface, 0, &request_data);
}

static bool get_integer(
    UVCContext *context,
    const ControlDefinition *control,
    uint8_t request_code,
    int64_t *value
) {
    uint8_t data[8] = {0};
    IOReturn result = request(
        context, control, request_code, kUSBIn, data, control->size
    );
    if (result != kIOReturnSuccess) {
        return false;
    }
    *value = decode_value(data, control->size, control->signed_value);
    return true;
}

static bool set_integer(
    UVCContext *context,
    const ControlDefinition *control,
    int64_t value
) {
    uint8_t data[8] = {0};
    encode_value(data, control->size, value);
    return request(
        context, control, UVC_SET_CUR, kUSBOut, data, control->size
    ) == kIOReturnSuccess;
}

static ControlState probe_control(UVCContext *context, const ControlDefinition *control) {
    ControlState state = {0};
    if (!advertised(context, control)) {
        return state;
    }
    uint8_t info = 0;
    if (request(context, control, UVC_GET_INFO, kUSBIn, &info, 1) != kIOReturnSuccess) {
        return state;
    }
    state.supported = (info & 0x01) != 0;
    state.settable = (info & 0x02) != 0;
    if (!state.supported) {
        return state;
    }
    state.has_minimum = get_integer(context, control, UVC_GET_MIN, &state.minimum);
    state.has_maximum = get_integer(context, control, UVC_GET_MAX, &state.maximum);
    state.has_step = get_integer(context, control, UVC_GET_RES, &state.step);
    state.has_default = get_integer(context, control, UVC_GET_DEF, &state.default_value);
    state.has_current = get_integer(context, control, UVC_GET_CUR, &state.current);
    return state;
}

static const ControlDefinition *find_control(const char *key) {
    size_t count = sizeof(CONTROLS) / sizeof(CONTROLS[0]);
    for (size_t index = 0; index < count; ++index) {
        if (strcmp(CONTROLS[index].key, key) == 0) {
            return &CONTROLS[index];
        }
    }
    return NULL;
}

static void copy_bitmap(uint8_t *target, size_t *target_size, const uint8_t *source, size_t size) {
    if (size > 8) {
        size = 8;
    }
    memcpy(target, source, size);
    *target_size = size;
}

static io_service_t find_camera_service(uint32_t location_id) {
    CFMutableDictionaryRef matching = IOServiceMatching(kIOUSBDeviceClassName);
    if (matching == NULL) {
        return IO_OBJECT_NULL;
    }
    CFMutableDictionaryRef properties = CFDictionaryCreateMutable(
        kCFAllocatorDefault, 2, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks
    );
    if (location_id != 0) {
        CFNumberRef location = CFNumberCreate(
            kCFAllocatorDefault, kCFNumberSInt32Type, &location_id
        );
        CFDictionarySetValue(
            properties, CFSTR(kUSBDevicePropertyLocationID), location
        );
        CFRelease(location);
    } else {
        int16_t vendor_id = CTVIDEO_CAMERA_VENDOR_ID;
        int16_t product_id = CTVIDEO_CAMERA_PRODUCT_ID;
        CFNumberRef vendor = CFNumberCreate(
            kCFAllocatorDefault, kCFNumberSInt16Type, &vendor_id
        );
        CFNumberRef product = CFNumberCreate(
            kCFAllocatorDefault, kCFNumberSInt16Type, &product_id
        );
        CFDictionarySetValue(properties, CFSTR(kUSBVendorID), vendor);
        CFDictionarySetValue(properties, CFSTR(kUSBProductID), product);
        CFRelease(vendor);
        CFRelease(product);
    }
    CFDictionarySetValue(matching, CFSTR(kIOPropertyMatchKey), properties);
    CFRelease(properties);

    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(
            kIOMainPortDefault, matching, &iterator
        ) != kIOReturnSuccess || iterator == IO_OBJECT_NULL) {
        return IO_OBJECT_NULL;
    }
    io_service_t device_service = IOIteratorNext(iterator);
    io_service_t second_service = IOIteratorNext(iterator);
    IOObjectRelease(iterator);
    if (second_service != IO_OBJECT_NULL) {
        IOObjectRelease(second_service);
        if (device_service != IO_OBJECT_NULL) {
            IOObjectRelease(device_service);
        }
        return IO_OBJECT_NULL;
    }
    return device_service;
}

static bool find_video_control_interface(uint32_t location_id, UVCContext *context) {
    io_service_t device_service = find_camera_service(location_id);
    if (device_service == IO_OBJECT_NULL) {
        return false;
    }

    IOCFPlugInInterface **device_plugin = NULL;
    IOUSBDeviceInterface **device_interface = NULL;
    SInt32 score = 0;
    kern_return_t kernel_result = IOCreatePlugInInterfaceForService(
        device_service, kIOUSBDeviceUserClientTypeID, kIOCFPlugInInterfaceID,
        &device_plugin, &score
    );
    if (kernel_result != kIOReturnSuccess || device_plugin == NULL) {
        IOObjectRelease(device_service);
        return false;
    }
    HRESULT query_result = (*device_plugin)->QueryInterface(
        device_plugin, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID),
        (LPVOID *)&device_interface
    );
    IODestroyPlugInInterface(device_plugin);
    if (query_result != 0 || device_interface == NULL) {
        IOObjectRelease(device_service);
        return false;
    }

    IOUSBFindInterfaceRequest interface_request = {
        .bInterfaceClass = kUSBVideoInterfaceClass,
        .bInterfaceSubClass = kUSBVideoControlSubClass,
        .bInterfaceProtocol = kIOUSBFindInterfaceDontCare,
        .bAlternateSetting = kIOUSBFindInterfaceDontCare,
    };
    io_iterator_t iterator = IO_OBJECT_NULL;
    IOReturn io_result = (*device_interface)->CreateInterfaceIterator(
        device_interface, &interface_request, &iterator
    );
    (*device_interface)->Release(device_interface);
    IOObjectRelease(device_service);
    if (io_result != kIOReturnSuccess || iterator == IO_OBJECT_NULL) {
        return false;
    }

    io_service_t interface_service = IOIteratorNext(iterator);
    IOObjectRelease(iterator);
    if (interface_service == IO_OBJECT_NULL) {
        return false;
    }

    IOCFPlugInInterface **interface_plugin = NULL;
    kernel_result = IOCreatePlugInInterfaceForService(
        interface_service, kIOUSBInterfaceUserClientTypeID,
        kIOCFPlugInInterfaceID, &interface_plugin, &score
    );
    IOObjectRelease(interface_service);
    if (kernel_result != kIOReturnSuccess || interface_plugin == NULL) {
        return false;
    }
    query_result = (*interface_plugin)->QueryInterface(
        interface_plugin, CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID),
        (LPVOID *)&context->interface
    );
    IODestroyPlugInInterface(interface_plugin);
    if (query_result != 0 || context->interface == NULL) {
        return false;
    }
    if ((*context->interface)->GetInterfaceNumber(
            context->interface, &context->interface_number
        ) != kIOReturnSuccess) {
        return false;
    }

    IOUSBDescriptorHeader *header = (*context->interface)->FindNextAssociatedDescriptor(
        context->interface, NULL, CS_INTERFACE
    );
    if (header != NULL) {
        const uint8_t *base = (const uint8_t *)header;
        if (base[2] == VC_HEADER && base[0] >= 7) {
            uint16_t total_length = read_le16(base + 5);
            const uint8_t *cursor = base + base[0];
            const uint8_t *end = base + total_length;
            while (cursor + 3 <= end && cursor[0] >= 3 && cursor + cursor[0] <= end) {
                if (cursor[1] == CS_INTERFACE && cursor[2] == VC_INPUT_TERMINAL
                        && cursor[0] >= 15) {
                    context->camera_terminal_id = cursor[3];
                    size_t bitmap_size = cursor[14];
                    if (15 + bitmap_size <= cursor[0]) {
                        copy_bitmap(
                            context->terminal_controls,
                            &context->terminal_controls_size,
                            cursor + 15,
                            bitmap_size
                        );
                    }
                } else if (cursor[1] == CS_INTERFACE
                        && cursor[2] == VC_PROCESSING_UNIT && cursor[0] >= 8) {
                    context->processing_unit_id = cursor[3];
                    size_t bitmap_size = cursor[7];
                    if (8 + bitmap_size <= cursor[0]) {
                        copy_bitmap(
                            context->processing_controls,
                            &context->processing_controls_size,
                            cursor + 8,
                            bitmap_size
                        );
                    }
                }
                cursor += cursor[0];
            }
        }
    }

    IOReturn open_result = (*context->interface)->USBInterfaceOpen(context->interface);
    if (open_result == kIOReturnSuccess) {
        context->opened_by_helper = true;
    } else if (open_result != kIOReturnExclusiveAccess) {
        return false;
    }
    return context->camera_terminal_id != 0 && context->processing_unit_id != 0;
}

static void close_context(UVCContext *context) {
    if (context->interface == NULL) {
        return;
    }
    if (context->opened_by_helper) {
        (*context->interface)->USBInterfaceClose(context->interface);
    }
    (*context->interface)->Release(context->interface);
    context->interface = NULL;
}

static void print_optional(bool available, int64_t value) {
    if (available) {
        printf("%" PRId64, value);
    } else {
        printf("-");
    }
}

static void print_control(UVCContext *context, const ControlDefinition *control) {
    ControlState state = probe_control(context, control);
    printf("CONTROL\t%s\t%s\t%d\t%d\t", control->key, control->display_name,
           state.supported ? 1 : 0, state.settable ? 1 : 0);
    print_optional(state.has_minimum, state.minimum);
    printf("\t");
    print_optional(state.has_maximum, state.maximum);
    printf("\t");
    print_optional(state.has_step, state.step);
    printf("\t");
    print_optional(state.has_default, state.default_value);
    printf("\t");
    print_optional(state.has_current, state.current);
    printf("\n");
}

static bool apply_assignment(UVCContext *context, const char *assignment) {
    const char *separator = strchr(assignment, '=');
    if (separator == NULL || separator == assignment) {
        fprintf(stderr, "Invalid assignment: %s\n", assignment);
        return false;
    }
    size_t key_length = (size_t)(separator - assignment);
    char key[64];
    if (key_length >= sizeof(key)) {
        return false;
    }
    memcpy(key, assignment, key_length);
    key[key_length] = '\0';
    const ControlDefinition *control = find_control(key);
    if (control == NULL) {
        fprintf(stderr, "Unknown control: %s\n", key);
        return false;
    }
    errno = 0;
    char *end = NULL;
    int64_t requested = strtoll(separator + 1, &end, 0);
    if (errno != 0 || end == separator + 1 || *end != '\0') {
        fprintf(stderr, "Invalid value for %s: %s\n", key, separator + 1);
        return false;
    }
    ControlState state = probe_control(context, control);
    if (!state.supported || !state.settable) {
        printf("SET\t%s\tUNSUPPORTED\t-\n", key);
        return false;
    }
    if ((state.has_minimum && requested < state.minimum)
            || (state.has_maximum && requested > state.maximum)) {
        printf("SET\t%s\tOUT_OF_RANGE\t-\n", key);
        return false;
    }
    if (!set_integer(context, control, requested)) {
        printf("SET\t%s\tFAILED\t-\n", key);
        return false;
    }
    int64_t actual = 0;
    if (!get_integer(context, control, UVC_GET_CUR, &actual)) {
        printf("SET\t%s\tNO_READBACK\t-\n", key);
        return false;
    }
    printf("SET\t%s\t%s\t%" PRId64 "\n", key,
           actual == requested ? "OK" : "MISMATCH", actual);
    return actual == requested;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <location-id> [control=value ...]\n", argv[0]);
        return 64;
    }
    errno = 0;
    char *end = NULL;
    unsigned long parsed_location = strtoul(argv[1], &end, 0);
    if (errno != 0 || end == argv[1] || *end != '\0' || parsed_location > UINT32_MAX) {
        fprintf(stderr, "Invalid USB location ID: %s\n", argv[1]);
        return 64;
    }

    UVCContext context = {0};
    if (!find_video_control_interface((uint32_t)parsed_location, &context)) {
        close_context(&context);
        if (parsed_location == 0) {
            fprintf(
                stderr,
                "Could not find exactly one CTvideo UVC camera "
                "(VID:PID 093A:2900)\n"
            );
        } else {
            fprintf(
                stderr,
                "Could not open the UVC VideoControl interface at 0x%08lx\n",
                parsed_location
            );
        }
        return 2;
    }

    bool assignments_ok = true;
    for (int index = 2; index < argc; ++index) {
        if (!apply_assignment(&context, argv[index])) {
            assignments_ok = false;
        }
    }
    size_t control_count = sizeof(CONTROLS) / sizeof(CONTROLS[0]);
    for (size_t index = 0; index < control_count; ++index) {
        print_control(&context, &CONTROLS[index]);
    }
    close_context(&context);
    return assignments_ok ? 0 : 3;
}
