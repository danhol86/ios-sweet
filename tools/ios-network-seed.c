/*
 * Isolated iOS Sweet QEMU DNS/IPv4 SystemConfiguration bootstrap.
 *
 * The experimental kernel already has working en0, IPv4 and TCP. However,
 * configd does not publish its active dynamic-store state. Without that,
 * iOS mDNSResponder cannot resolve ordinary hostnames.
 *
 * Run as root only, on the user-owned iOS Sweet guest; never attempt to
 * change the network settings of a physical phone. Does not collect URLs,
 * passwords, tokens or packet payloads.
 *
 * In an isolated compatibility test this binary may temporarily replace
 * ReportCrash; in that mode it executes the original Apple binary promptly
 * after seeding and preserves its arguments and normal functionality.
 */
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>
#include <CoreFoundation/CoreFoundation.h>

typedef void *(*store_create_fn)(CFAllocatorRef, CFStringRef, void *, void *);
typedef Boolean (*store_set_fn)(void *, CFStringRef, CFPropertyListRef);
typedef CFPropertyListRef (*store_get_fn)(void *, CFStringRef);

static const CFStringRef service = CFSTR("CA9E6055-8C86-514A-B8BE-57D7F8A04B1B");

static int is_qemu_guest(void)
{
    struct ifaddrs *interfaces = NULL;
    if (getifaddrs(&interfaces) != 0) return 0;
    int found = 0;
    for (const struct ifaddrs *item = interfaces; item; item = item->ifa_next) {
        if (!item->ifa_name || !item->ifa_addr ||
            item->ifa_addr->sa_family != AF_INET ||
            strcmp(item->ifa_name, "en0") != 0) continue;
        struct in_addr expected;
        inet_pton(AF_INET, "10.0.2.15", &expected);
        const struct sockaddr_in *a = (const struct sockaddr_in *)item->ifa_addr;
        found = (a->sin_addr.s_addr == expected.s_addr);
        if (found) break;
    }
    freeifaddrs(interfaces);
    return found;
}

static CFMutableDictionaryRef dictionary(void)
{
    return CFDictionaryCreateMutable(NULL, 0,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
}

static int write_state(void *store, store_set_fn set, store_get_fn get)
{
    int success = 1;
    CFMutableDictionaryRef serviceIPv4 = dictionary();
    const void *addr_value[] = {CFSTR("10.0.2.15")};
    const void *mask_value[] = {CFSTR("255.255.255.0")};
    CFArrayRef addr = CFArrayCreate(NULL, addr_value, 1, &kCFTypeArrayCallBacks);
    CFArrayRef mask = CFArrayCreate(NULL, mask_value, 1, &kCFTypeArrayCallBacks);
    CFDictionarySetValue(serviceIPv4, CFSTR("Addresses"), addr);
    CFDictionarySetValue(serviceIPv4, CFSTR("SubnetMasks"), mask);
    CFDictionarySetValue(serviceIPv4, CFSTR("Router"), CFSTR("10.0.2.2"));
    CFDictionarySetValue(serviceIPv4, CFSTR("InterfaceName"), CFSTR("en0"));
    if (!set(store, CFSTR(
        "State:/Network/Service/CA9E6055-8C86-514A-B8BE-57D7F8A04B1B/IPv4"),
        serviceIPv4)) success = 0;
    CFRelease(serviceIPv4);
    CFRelease(addr);
    CFRelease(mask);

    CFMutableDictionaryRef globalIPv4 = dictionary();
    CFDictionarySetValue(globalIPv4, CFSTR("PrimaryService"), service);
    CFDictionarySetValue(globalIPv4, CFSTR("PrimaryInterface"), CFSTR("en0"));
    CFDictionarySetValue(globalIPv4, CFSTR("Router"), CFSTR("10.0.2.2"));
    if (!set(store, CFSTR("State:/Network/Global/IPv4"), globalIPv4))
        success = 0;
    CFRelease(globalIPv4);

    CFMutableDictionaryRef link = dictionary();
    CFDictionarySetValue(link, CFSTR("Active"), kCFBooleanTrue);
    if (!set(store, CFSTR("State:/Network/Interface/en0/Link"), link))
        success = 0;
    CFRelease(link);

    CFMutableDictionaryRef dns = dictionary();
    const void *server_array[] = {CFSTR("10.0.2.3")};
    CFArrayRef servers = CFArrayCreate(
        NULL, server_array, 1, &kCFTypeArrayCallBacks);
    CFDictionarySetValue(dns, CFSTR("ServerAddresses"), servers);
    CFDictionarySetValue(dns, CFSTR("InterfaceName"), CFSTR("en0"));
    if (!set(store, CFSTR(
        "State:/Network/Service/CA9E6055-8C86-514A-B8BE-57D7F8A04B1B/DNS"),
        dns)) success = 0;
    if (!set(store, CFSTR("State:/Network/Global/DNS"), dns))
        success = 0;
    CFRelease(dns);
    CFRelease(servers);

    if (get) {
        CFPropertyListRef v = get(store, CFSTR("State:/Network/Global/DNS"));
        if (!v) success = 0;
        if (v) CFRelease(v);
        v = get(store, CFSTR("State:/Network/Global/IPv4"));
        if (!v) success = 0;
        if (v) CFRelease(v);
    }
    return success;
}

static void setup_log(void)
{
    int fd = open("/private/var/mobile/Library/iossweet-netseed.log",
        O_WRONLY | O_CREAT | O_APPEND | O_SYNC, 0600);
    if (fd < 0) fd = open("/dev/console", O_WRONLY | O_NOCTTY);
    if (fd >= 0) {
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        if (fd > STDERR_FILENO) close(fd);
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}

static int seed_once(void)
{
    if (geteuid() != 0 || !is_qemu_guest()) {
        puts("IOS_NETSEED_SKIPPED: only root QEMU en0 10.0.2.15");
        return 2;
    }
    void *lib = dlopen(
        "/System/Library/Frameworks/SystemConfiguration.framework/SystemConfiguration",
        RTLD_LAZY);
    if (!lib) return 3;
    store_create_fn create = (store_create_fn)dlsym(lib, "SCDynamicStoreCreate");
    store_set_fn set = (store_set_fn)dlsym(lib, "SCDynamicStoreSetValue");
    store_get_fn get = (store_get_fn)dlsym(lib, "SCDynamicStoreCopyValue");
    if (!create || !set) {
        dlclose(lib);
        return 4;
    }
    void *store = create(NULL, CFSTR("iossweet-qemu-network"), NULL, NULL);
    if (!store) {
        dlclose(lib);
        return 5;
    }
    int ok = write_state(store, set, get);
    CFRelease((CFTypeRef)store);
    dlclose(lib);
    return ok ? 0 : 6;
}

int main(int argc, char **argv)
{
    const int wrapper = argc > 0 && argv[0] &&
        strstr(argv[0], "/ReportCrash") != NULL;
    setup_log();
    printf("IOS_NETSEED_START uid=%ld mode=%s\n",
           (long)geteuid(), wrapper ? "reportcrash-wrapper" : "standalone");
    int last = 1;
    int attempts = wrapper ? 1 : 35;
    for (int i = 0; i < attempts; ++i) {
        last = seed_once();
        if (last == 0 || last == 2) break;
        sleep(2);
    }
    printf("IOS_NETSEED_DONE rc=%d\n", last);
    if (wrapper) {
        /* Only the disposable image installer creates this backup. */
        const char *original =
            "/System/Library/CoreServices/ReportCrash.iossweet-original";
        if (access(original, X_OK) != 0) {
            puts("IOS_NETSEED_ORIGINAL_REPORTCRASH_NOT_FOUND");
            return 79;
        }
        argv[0] = (char *)original;
        execv(original, argv);
        printf("IOS_NETSEED_REPORTCRASH_EXEC_FAILED errno=%d\n", errno);
        return 80;
    }
    return last;
}
