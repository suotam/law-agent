# Pinned deliberately: docling-serve renames request options between releases
# (ocr_engine -> ocr_preset), which silently changes what the client must send.
FROM ghcr.io/docling-project/docling-serve-cpu:v1.29.0

USER root

# The base image already ships Tesseract and its Python bindings, but only the
# English and OSD models. Czech legal scans need ces.traineddata.
RUN dnf install -y tesseract-langpack-ces \
    && dnf clean all \
    && rm -rf /var/cache/dnf

USER 1001
