/*
 * Diagnostic-only networking probe for a disposable, user-owned iOS Sweet
 * QEMU guest. No data collection, credentials, or external telemetry.
 *
 * Build for arm64 iOS with Apple's public SDK, install in a private overlay,
 * and examine only the locally written stdout file from launchd.
 */
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netdb.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include <SystemConfiguration/SCNetworkReachability.h>

static void timestamp(void)
{
    time_t t = time(NULL);
    printf("iossweet-probe timestamp=%lld\n", (long long)t);
}

static void interfaces(void)
{
    struct ifaddrs *list = NULL;
    int rc = getifaddrs(&list);
    printf("getifaddrs rc=%d errno=%d\n", rc, rc ? errno : 0);
    if (rc != 0) return;
    for (struct ifaddrs *item = list; item; item = item->ifa_next) {
        if (!item->ifa_addr) continue;
        int family = item->ifa_addr->sa_family;
        if (family != AF_INET && family != AF_INET6) continue;
        char addr[INET6_ADDRSTRLEN] = {0};
        const void *ip = family == AF_INET ?
            (const void *)&((struct sockaddr_in *)item->ifa_addr)->sin_addr :
            (const void *)&((struct sockaddr_in6 *)item->ifa_addr)->sin6_addr;
        inet_ntop(family, ip, addr, sizeof(addr));
        printf("interface name=%s addr=%s flags=0x%x\n",
               item->ifa_name ? item->ifa_name : "(null)", addr, item->ifa_flags);
    }
    freeifaddrs(list);
}

static void reachability(void)
{
    struct sockaddr_in remote;
    memset(&remote, 0, sizeof(remote));
    remote.sin_len = sizeof(remote);
    remote.sin_family = AF_INET;
    inet_pton(AF_INET, "1.1.1.1", &remote.sin_addr);
    SCNetworkReachabilityRef ref = SCNetworkReachabilityCreateWithAddress(
        NULL, (const struct sockaddr *)&remote);
    if (!ref) { puts("reachability_create_ip=null"); return; }
    SCNetworkReachabilityFlags flags = 0;
    Boolean ok = SCNetworkReachabilityGetFlags(ref, &flags);
    printf("reachability_ip ok=%d flags=0x%x\n", (int)ok, (unsigned)flags);
    CFRelease(ref);
}

static void direct_connect(void)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        printf("tcp_socket_error=%d\n", errno);
        return;
    }
    int flags = fcntl(fd, F_GETFL);
    if (flags >= 0) (void)fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    struct sockaddr_in remote;
    memset(&remote, 0, sizeof(remote));
    remote.sin_family = AF_INET;
    remote.sin_len = sizeof(remote);
    remote.sin_port = htons(443);
    inet_pton(AF_INET, "1.1.1.1", &remote.sin_addr);
    errno = 0;
    int rc = connect(fd, (struct sockaddr *)&remote, sizeof(remote));
    int e = errno;
    printf("tcp_connect_1.1.1.1:443 rc=%d errno=%d\n", rc, e);
    if (rc < 0 && e == EINPROGRESS) {
        struct pollfd waitfd = {.fd = fd, .events = POLLOUT};
        int n = poll(&waitfd, 1, 5000);
        int err = -1;
        socklen_t size = sizeof(err);
        if (n > 0 && getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &size) < 0)
            err = errno;
        printf("tcp_connect_result poll=%d revents=0x%x so_error=%d\n",
               n, (unsigned)waitfd.revents, err);
    }
    close(fd);
}

static int dns_lookup(void)
{
    struct addrinfo hints = {0}, *results = NULL;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    errno = 0;
    int rc = getaddrinfo("google.com", "443", &hints, &results);
    printf("dns_google.com rc=%d system_errno=%d\n", rc, errno);
    if (rc == 0) {
        for (const struct addrinfo *a = results; a; a = a->ai_next) {
            char ip[INET_ADDRSTRLEN] = {0};
            if (a->ai_family == AF_INET) {
                inet_ntop(AF_INET,
                    &((const struct sockaddr_in *)a->ai_addr)->sin_addr,
                    ip, sizeof(ip));
                printf("dns_google.com answer=%s\n", ip);
                break;
            }
        }
        freeaddrinfo(results);
    }
    return rc;
}

static void try_private_dns_store(void)
{
    /* SCDynamicStore mutation APIs are explicitly unavailable in the
       public iOS SDK. Probe at runtime only; do not claim they exist.
       This runs exclusively on a disposable, locally-owned iOS disk. */
    typedef void *(*create_fn)(CFAllocatorRef, CFStringRef, void *, void *);
    typedef Boolean (*set_fn)(void *, CFStringRef, CFPropertyListRef);
    typedef int (*scerror_fn)(void);
    typedef CFPropertyListRef (*copy_fn)(void *, CFStringRef);
    static void *kept_store = NULL;
    void *framework = dlopen(
        "/System/Library/Frameworks/SystemConfiguration.framework/SystemConfiguration",
        RTLD_LAZY);
    create_fn create = (create_fn)dlsym(
        framework ? framework : RTLD_DEFAULT, "SCDynamicStoreCreate");
    set_fn set = (set_fn)dlsym(
        framework ? framework : RTLD_DEFAULT, "SCDynamicStoreSetValue");
    scerror_fn scerror = (scerror_fn)dlsym(
        framework ? framework : RTLD_DEFAULT, "SCError");
    copy_fn copy = (copy_fn)dlsym(
        framework ? framework : RTLD_DEFAULT, "SCDynamicStoreCopyValue");
    printf("private_dns_store uid=%ld euid=%ld error_symbol=%d copy_symbol=%d\n",
           (long)getuid(), (long)geteuid(), scerror != NULL, copy != NULL);
    printf("private_dns_store create_symbol=%d set_symbol=%d\n",
           create != NULL, set != NULL);
    if (!create || !set) {
        if (framework) dlclose(framework);
        return;
    }
    void *store = create(NULL, CFSTR("iossweet-test-dns"), NULL, NULL);
    if (!store) {
        printf("private_dns_store create_failed sc_error=%d\n",
               scerror ? scerror() : -1);
        dlclose(framework);
        return;
    }
    if (copy) {
        const CFStringRef keys[3] = {
            CFSTR("State:/Network/Global/DNS"),
            CFSTR("State:/Network/Global/IPv4"),
            CFSTR("State:/Network/Service/CA9E6055-8C86-514A-B8BE-57D7F8A04B1B/DNS")
        };
        for (unsigned i = 0; i < 3; ++i) {
            CFPropertyListRef entry = copy(store, keys[i]);
            printf("private_dns_store existing_key=%u present=%d sc_error=%d\n",
                   i, entry != NULL, scerror ? scerror() : -1);
            if (entry) CFRelease(entry);
        }
    }
    /* QEMU already gives en0 a real BSD address/default route. iOS does
       not have the corresponding *dynamic* service/primary-interface
       announcements. Recreate those, only in the isolated test guest. */
    CFMutableDictionaryRef serviceIPv4 = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    const void *hostAddresses[1] = { CFSTR("10.0.2.15") };
    const void *hostMasks[1] = { CFSTR("255.255.255.0") };
    CFArrayRef addresses = CFArrayCreate(
        NULL, hostAddresses, 1, &kCFTypeArrayCallBacks);
    CFArrayRef masks = CFArrayCreate(
        NULL, hostMasks, 1, &kCFTypeArrayCallBacks);
    CFDictionarySetValue(serviceIPv4, CFSTR("Addresses"), addresses);
    CFDictionarySetValue(serviceIPv4, CFSTR("SubnetMasks"), masks);
    CFDictionarySetValue(serviceIPv4, CFSTR("Router"), CFSTR("10.0.2.2"));
    CFDictionarySetValue(serviceIPv4, CFSTR("InterfaceName"), CFSTR("en0"));
    Boolean ok = set(store,
        CFSTR("State:/Network/Service/CA9E6055-8C86-514A-B8BE-57D7F8A04B1B/IPv4"),
        serviceIPv4);
    printf("private_dns_store service_ipv4_set=%d sc_error=%d\n",
           (int)ok, ok ? 0 : (scerror ? scerror() : -1));
    CFRelease(serviceIPv4);
    CFRelease(addresses);
    CFRelease(masks);

    CFMutableDictionaryRef globalIPv4 = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(globalIPv4, CFSTR("PrimaryService"),
        CFSTR("CA9E6055-8C86-514A-B8BE-57D7F8A04B1B"));
    CFDictionarySetValue(globalIPv4, CFSTR("PrimaryInterface"),
        CFSTR("en0"));
    CFDictionarySetValue(globalIPv4, CFSTR("Router"), CFSTR("10.0.2.2"));
    ok = set(store, CFSTR("State:/Network/Global/IPv4"), globalIPv4);
    printf("private_dns_store global_ipv4_set=%d sc_error=%d\n",
           (int)ok, ok ? 0 : (scerror ? scerror() : -1));
    CFRelease(globalIPv4);

    CFMutableDictionaryRef link = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(link, CFSTR("Active"), kCFBooleanTrue);
    ok = set(store, CFSTR("State:/Network/Interface/en0/Link"), link);
    printf("private_dns_store ethernet_link_set=%d sc_error=%d\n",
           (int)ok, ok ? 0 : (scerror ? scerror() : -1));
    CFRelease(link);

    CFMutableDictionaryRef dns = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    const void *server[1] = {CFSTR("10.0.2.3")};
    CFArrayRef servers = CFArrayCreate(
        NULL, server, 1, &kCFTypeArrayCallBacks);
    CFDictionarySetValue(dns, CFSTR("ServerAddresses"), servers);
    CFDictionarySetValue(dns, CFSTR("InterfaceName"), CFSTR("en0"));
    ok = set(store, CFSTR("State:/Network/Global/DNS"), dns);
    printf("private_dns_store global_dns_set=%d sc_error=%d\n",
           (int)ok, ok ? 0 : (scerror ? scerror() : -1));
    CFStringRef key = CFSTR(
        "State:/Network/Service/CA9E6055-8C86-514A-B8BE-57D7F8A04B1B/DNS");
    ok = set(store, key, dns);
    printf("private_dns_store service_dns_set=%d sc_error=%d\n",
           (int)ok, ok ? 0 : (scerror ? scerror() : -1));
    if (copy) {
        CFPropertyListRef verify = copy(
            store, CFSTR("State:/Network/Global/IPv4"));
        printf("private_dns_store verify_global_ipv4=%d\n", verify != NULL);
        if (verify) CFRelease(verify);
        verify = copy(store, CFSTR("State:/Network/Global/DNS"));
        printf("private_dns_store verify_global_dns=%d\n", verify != NULL);
        if (verify) CFRelease(verify);
    }
    CFRelease(servers);
    CFRelease(dns);
    /* Keep the configd session alive for the subsequent resolver request.
       There must not be a time-of-check/time-of-use gap in this experiment. */
    kept_store = store;
    (void)kept_store;
    if (framework) dlclose(framework);
}

int main(void)
{
    /* This guest's stock launchd jobs do not inherit a readable stdout.
       Persist results in the disposable guest for offline inspection. */
    /* /var/tmp is purged by some guest boot services. Use a persistent,
       per-UID diagnostic file inside this private guest overlay instead. */
    char log_path[192];
    (void)snprintf(log_path, sizeof(log_path),
        "/private/var/mobile/Library/iossweet-netprobe-%ld.log",
        (long)geteuid());
    int logfile = open(log_path, O_WRONLY | O_CREAT | O_APPEND | O_SYNC, 0600);
    int log_errno = errno;
    if (logfile < 0) {
        /* Some iOS service sandboxes forbid creating files in /var/tmp.
           The test image has a world-writable /dev/console; use it to
           retain diagnostics in QEMU's local kernel/console capture. */
        logfile = open("/dev/console", O_WRONLY | O_NOCTTY);
    }
    if (logfile >= 0) {
        (void)dup2(logfile, STDOUT_FILENO);
        (void)dup2(logfile, STDERR_FILENO);
        if (logfile > STDERR_FILENO) close(logfile);
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
    puts("IOS_SWEET_NETWORK_PROBE_START");
    printf("log_path=%s log_file_open_errno=%d log_target_available=%d\n",
           log_path, log_errno, logfile >= 0);
    timestamp();
    for (int attempt = 1; attempt <= 4; ++attempt) {
        printf("attempt=%d\n", attempt);
        interfaces();
        direct_connect();
        /* Publish diagnostic config BEFORE making getaddrinfo, since the
           broken iOS resolver can block for a long time waiting for DNS. */
        if (attempt == 1) {
            try_private_dns_store();
            sleep(2);
        }
        printf("dns_after_store_attempt:\n");
        (void)dns_lookup();
        reachability();
        if (attempt != 4) sleep(10);
    }
    puts("IOS_SWEET_NETWORK_PROBE_DONE");
    return 0;
}
