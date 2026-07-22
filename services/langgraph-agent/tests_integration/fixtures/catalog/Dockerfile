FROM python:3.12-slim AS generator
WORKDIR /gen
COPY generate_catalog.py .
RUN python3 generate_catalog.py /site/catalog

FROM nginx:alpine
COPY --from=generator /site /usr/share/nginx/html
