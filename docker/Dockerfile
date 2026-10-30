FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates coreutils llvm python3 qemu-system-arm qemu-utils \
    libguestfs-tools linux-image-generic \
 && rm -rf /var/lib/apt/lists/*
COPY docker/entrypoint.sh /usr/local/bin/iossweet-entrypoint
COPY docker/prepare-network.sh /usr/local/bin/iossweet-prepare-network
COPY docker/network/iossweet-net-seed /usr/local/share/iossweet-net-seed
RUN chmod 755 /usr/local/bin/iossweet-entrypoint \
              /usr/local/bin/iossweet-prepare-network \
              /usr/local/share/iossweet-net-seed
WORKDIR /app
EXPOSE 8099
ENTRYPOINT ["/usr/local/bin/iossweet-entrypoint"]
