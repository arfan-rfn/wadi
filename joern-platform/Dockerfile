# wadi-joern image (§5.1): stock, pinned Joern + the wadi jar. Never a fork (P5).
#
# JOERN_VERSION here MUST equal `joernVersion` in build.sbt — one pin across
# the sbt build, this image, and the release set (§13). The upstream container
# registry only publishes rolling tags (nightly/master), so the exact release
# zip is installed instead — rolling releases change internal APIs freely and
# our jar is compiled against exactly this version.

FROM sbtscala/scala-sbt:eclipse-temurin-21.0.5_11_1.10.7_3.6.2 AS build
WORKDIR /platform
COPY build.sbt ./
COPY project ./project
RUN sbt -batch update
COPY src ./src
RUN sbt -batch assembly

FROM eclipse-temurin:21-jdk-noble
ARG JOERN_VERSION=4.0.593
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends unzip curl \
    && rm -rf /var/lib/apt/lists/* \
    && case "$TARGETARCH" in \
         amd64) JOERN_ARCH=x86_64 ;; \
         arm64) JOERN_ARCH=arm64 ;; \
         *) echo "unsupported arch: $TARGETARCH" && exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/joernio/joern/releases/download/v${JOERN_VERSION}/joern-cli-linux-${JOERN_ARCH}.zip" -o /tmp/joern.zip \
    && unzip -q /tmp/joern.zip -d /opt \
    && rm /tmp/joern.zip \
    && ln -s /opt/joern-cli/joern /usr/local/bin/joern

# Our extensions ride Joern's own classpath: passes, packs, pipeline, export.
COPY --from=build /platform/target/scala-*/wadi-joern-platform.jar /opt/joern-cli/lib/wadi-joern-platform.jar

# Shared volumes (must be mounted at the same paths in the worker, §13 topology).
VOLUME ["/workspace", "/cpg-cache"]

EXPOSE 8080
# The CPGQL server is not a security boundary (upstream docs) — it is only ever
# reachable on the internal compose network, never published to the host (§13).
ENTRYPOINT ["joern", "--server", "--server-host", "0.0.0.0", "--server-port", "8080"]
