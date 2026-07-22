FROM python:3.12-slim AS generator
WORKDIR /gen
COPY generate_docs.py .
RUN python3 generate_docs.py /site/docs

FROM nginx:alpine
COPY --from=generator /site /usr/share/nginx/html
