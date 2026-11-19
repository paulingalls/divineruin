#import <CoreAudio/CoreAudio.h>
#import <Foundation/Foundation.h>
#import <dlfcn.h>
#import <objc/message.h>

static void require(BOOL condition, NSString *message) {
    if (!condition) {
        @throw [NSException exceptionWithName:@"NativeAudioRoute" reason:message userInfo:nil];
    }
}

static SEL method(id receiver, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    require([receiver respondsToSelector:selector],
            [NSString stringWithFormat:@"CoreSimulator audio requires %@ on %@", name, [receiver class]]);
    return selector;
}

static id readProperty(id receiver, NSString *name) {
    id value = ((id (*)(id, SEL))objc_msgSend)(receiver, method(receiver, name));
    require(value != nil, [NSString stringWithFormat:@"CoreSimulator returned no %@", name]);
    return value;
}

static NSString *defaultUID(AudioObjectPropertySelector selector) {
    AudioObjectPropertyAddress address = {selector, kAudioObjectPropertyScopeGlobal,
                                         kAudioObjectPropertyElementMain};
    AudioDeviceID device = kAudioObjectUnknown;
    UInt32 size = sizeof(device);
    OSStatus status = AudioObjectGetPropertyData(kAudioObjectSystemObject, &address, 0, NULL, &size, &device);
    require(status == noErr && device != kAudioObjectUnknown,
            [NSString stringWithFormat:@"CoreAudio default device unavailable (%d)", status]);

    address.mSelector = kAudioDevicePropertyDeviceUID;
    CFStringRef uid = NULL;
    size = sizeof(uid);
    status = AudioObjectGetPropertyData(device, &address, 0, NULL, &size, &uid);
    require(status == noErr && uid != NULL,
            [NSString stringWithFormat:@"CoreAudio default device UID unavailable (%d)", status]);
    return CFBridgingRelease(uid);
}

static id audioDescriptor(NSString *developerDir, NSString *udid) {
    const char *framework = "/Library/Developer/PrivateFrameworks/CoreSimulator.framework/CoreSimulator";
    void *handle = dlopen(framework, RTLD_NOW);
    if (!handle) require(NO, [NSString stringWithFormat:@"Loading CoreSimulator: %s", dlerror()]);
    Class service = NSClassFromString(@"SimServiceContext");
    NSError *error = nil;
    SEL contextMethod = method(service, @"sharedServiceContextForDeveloperDir:error:");
    id context = ((id (*)(id, SEL, id, NSError **))objc_msgSend)(service, contextMethod, developerDir, &error);
    require(context != nil, [NSString stringWithFormat:@"CoreSimulator context: %@", error]);
    SEL deviceSetMethod = method(context, @"defaultDeviceSetWithError:");
    id devices = ((id (*)(id, SEL, NSError **))objc_msgSend)(context, deviceSetMethod, &error);
    require(devices != nil, [NSString stringWithFormat:@"CoreSimulator device set: %@", error]);
    for (id device in readProperty(devices, @"availableDevices")) {
        if (![readProperty(device, @"UDID") isEqual:[[NSUUID alloc] initWithUUIDString:udid]]) continue;
        for (id port in readProperty(readProperty(device, @"io"), @"ioPorts")) {
            if ([readProperty(port, @"portIdentifier") isEqual:@"com.apple.CoreSimulator.Audio.HostRoute"]) {
                return readProperty(port, @"descriptor");
            }
        }
        require(NO, [NSString stringWithFormat:@"Simulator %@ has no audio HostRoute port", udid]);
    }
    require(NO, [NSString stringWithFormat:@"Simulator %@ unavailable to CoreSimulator", udid]);
    return nil;
}

static void routeInput(id descriptor, NSString *uid) {
    SEL route = method(descriptor, @"routeGuestDeviceScope:toHostDeviceUID:completionQueue:completionHandler:");
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    __block NSError *failure = nil;
    void (^completion)(NSError *) = ^(NSError *error) {
        failure = error;
        dispatch_semaphore_signal(done);
    };
    // CoreSimulator uses scope 1 for guest input.
    ((void (*)(id, SEL, unsigned long, id, dispatch_queue_t, id))objc_msgSend)(
        descriptor, route, 1, uid, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), completion);
    require(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC)) == 0,
            @"CoreSimulator audio routing timed out");
    require(failure == nil, [NSString stringWithFormat:@"CoreSimulator input routing: %@", failure]);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        @try {
            require(argc == 3 || argc == 4, @"usage: native-audio-route developer_dir udid [input_uid]");
            id descriptor = audioDescriptor(@(argv[1]), @(argv[2]));
            if (argc == 4) routeInput(descriptor, @(argv[3]));
            NSMutableArray *devices = [NSMutableArray array];
            for (id host in readProperty(descriptor, @"availableHostDevices")) {
                [devices addObject:@{@"uid": readProperty(host, @"uniqueIdentifier"), @"name": readProperty(host, @"name")}];
            }
            NSDictionary *state = @{
                @"guestInput": readProperty(descriptor, @"guestInputHostDeviceUID"),
                @"guestOutput": readProperty(descriptor, @"guestOutputHostDeviceUID"),
                @"hostInput": defaultUID(kAudioHardwarePropertyDefaultInputDevice),
                @"hostOutput": defaultUID(kAudioHardwarePropertyDefaultOutputDevice),
                @"effectiveOutput": readProperty(descriptor, @"effectiveDefaultOutputDeviceUID"),
                @"devices": devices
            };
            NSError *error = nil;
            NSData *json = [NSJSONSerialization dataWithJSONObject:state options:0 error:&error];
            require(json != nil, [NSString stringWithFormat:@"Serializing audio route: %@", error]);
            fwrite(json.bytes, 1, json.length, stdout);
            return 0;
        } @catch (NSException *error) {
            fprintf(stderr, "%s\n", error.reason.UTF8String);
            return 1;
        }
    }
}
