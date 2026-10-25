FROM asia-northeast1-docker.pkg.dev/mapilog-509017/mapilog/daily-training-hill-view@sha256:0c6fe49ba88aae8fcc07628757cf272c856aec2fda16f660a9404890a40f5d3b
COPY --chown=10001:10001 run_tasks.py /tmp/run_tasks.py
COPY --chown=10001:10001 patch_runtime.py /tmp/patch_runtime.py
COPY --chown=10001:10001 verify_runtime.py /tmp/verify_jeju_runtime.py
USER 10001:10001
RUN python /tmp/patch_runtime.py && python /tmp/verify_jeju_runtime.py
