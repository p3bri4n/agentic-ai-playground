FROM python:3.12-slim

# Client Docker CLI nécessaire pour spawn les conteneurs MCP via le socket
# monté (voir app/main.py, _run_on_server, command="docker"). Copié depuis
# l'image officielle docker:cli plutôt qu'installé via apt : le paquet
# docker.io du dépôt Debian (trixie) n'installe que le démon (dockerd) et
# docker-proxy, PAS le binaire client /usr/bin/docker lui-même (découpage de
# paquet incomplet constaté empiriquement — which docker échouait malgré une
# installation apt "réussie" sans erreur). Cette image ne fait tourner aucun
# démon Docker, seulement le client contre le socket hôte monté.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
