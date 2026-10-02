# Implesia Mart Backend — local shortcuts (https://github.com/casey/just)
#
# Usage: run commands from this directory.
set shell := ["bash", "-euo", "pipefail", "-c"]

compose := "docker compose"
api_port := "8001"

# Create .env, start Postgres, Redis, and the API, then create the admin user.
dev-setup:
	#!/usr/bin/env bash
	set -euo pipefail
	cd "{{justfile_directory()}}"

	command -v docker >/dev/null 2>&1 || { echo "Error: docker is not installed."; exit 1; }
	docker info >/dev/null 2>&1 || { echo "Error: Docker is not running."; exit 1; }

	if [[ ! -f .env ]]; then
		cp .env.example .env
		echo "Created .env from .env.example"
	else
		echo ".env already exists (left unchanged)"
	fi

	if grep -q '^SECRET_KEY=change-me-in-production$' .env; then
		key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
		tmp="$(mktemp)"
		awk -v key="$key" 'BEGIN { FS = OFS = "=" } $1 == "SECRET_KEY" { $2 = key } { print }' .env >"$tmp"
		mv "$tmp" .env
		echo "Wrote a local SECRET_KEY into .env"
	fi

	# pydantic and Compose accept unquoted values with spaces. Bash `source` does not.
	env_get() {
		local key="$1"
		local default="$2"
		local line value
		line="$(grep -E "^${key}=" .env | tail -n1 || true)"
		if [[ -z "$line" ]]; then
			printf '%s' "$default"
			return
		fi
		value="${line#*=}"
		value="${value%\"}"
		value="${value#\"}"
		value="${value%\'}"
		value="${value#\'}"
		printf '%s' "$value"
	}

	pg_port="$(env_get POSTGRES_PORT 5434)"
	redis_port="$(env_get REDIS_HOST_PORT 6381)"
	api_port="{{api_port}}"

	port_owned_by_us() {
		local port="$1"
		local service="$2"
		local container_port="$3"
		local published
		published="$({{compose}} port "$service" "$container_port" 2>/dev/null | awk -F: '{print $NF}' || true)"
		[[ -n "$published" && "$published" == "$port" ]]
	}

	check_port() {
		local port="$1"
		local service="$2"
		local container_port="$3"
		if ss -tlnH "sport = :${port}" 2>/dev/null | grep -q .; then
			if ! port_owned_by_us "$port" "$service" "$container_port"; then
				echo "ERROR: port ${port} is already in use, so ${service} cannot start."
				exit 1
			fi
		fi
	}

	check_port "$pg_port" postgres 5432
	check_port "$redis_port" redis 6379
	check_port "$api_port" api 8000

	echo "Starting Postgres, Redis, and the API..."
	if ! {{compose}} up -d --build --wait; then
		echo "Error: services did not become healthy. API logs:"
		{{compose}} logs --tail 80 api || true
		exit 1
	fi

	if ! curl -fsS "http://127.0.0.1:${api_port}/health/live" >/dev/null; then
		echo "Error: API is up in Docker but http://127.0.0.1:${api_port}/health/live did not answer."
		{{compose}} logs --tail 80 api || true
		exit 1
	fi

	email="$(env_get FIRST_SUPERUSER_EMAIL admin@implesia.com)"
	password="$(env_get FIRST_SUPERUSER_PASSWORD change-me-too)"

	echo ""
	echo "==================================================="
	echo "Dev setup complete"
	echo ""
	echo "  API:     http://127.0.0.1:${api_port}"
	echo "  Docs:    http://127.0.0.1:${api_port}/docs"
	echo "  Health:  http://127.0.0.1:${api_port}/health/live"
	echo "  Login:   ${email} / ${password}"
	echo ""
	echo "  Bruno environment Local uses the same login."
	echo "  just down    # stop the API, Postgres, and Redis"
	echo "==================================================="

# Stop the API, Postgres, and Redis. Database volumes are kept.
down:
	{{compose}} down
