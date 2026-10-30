/*
 * Diagnostic-only networking probe for a disposable, user-owned iOS Sweet
 * QEMU guest. No data collection, credentials, or external telemetry.
 *
 * Build for arm64 iOS with Apple's public SDK, install in a private overlay,
 * and examine only the locally written stdout file from launchd.
 */
#include <arpa/inet.h>
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

static void dns_lookup(void)
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
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
    puts("IOS_SWEET_NETWORK_PROBE_START");
    timestamp();
    for (int attempt = 1; attempt <= 4; ++attempt) {
        printf("attempt=%d\n", attempt);
        interfaces();
        reachability();
        direct_connect();
        dns_lookup();
        if (attempt != 4) sleep(10);
    }
    puts("IOS_SWEET_NETWORK_PROBE_DONE");
    return 0;
}
