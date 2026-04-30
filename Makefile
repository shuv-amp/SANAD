SHELL := /bin/bash

.PHONY: backend frontend fixtures test-api build-web validate demo-check reset-demo smoke-tmt smoke-tmt-directions validate-tamang-proof validate-language-coverage docker-up docker-down

backend:
	cd apps/api && source .venv/bin/activate && uvicorn sanad_api.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd apps/web && npm run dev -- --host 127.0.0.1 --port 5173

fixtures:
	cd apps/api && source .venv/bin/activate && python scripts/create_demo_fixtures.py

test-api:
	cd apps/api && source .venv/bin/activate && pytest

build-web:
	cd apps/web && npm run build

validate:
	cd apps/api && source .venv/bin/activate && python scripts/validate_demo_flow.py

demo-check: test-api build-web validate

reset-demo:
	bash scripts/reset_demo_state.sh

smoke-tmt:
	cd apps/api && source .venv/bin/activate && SANAD_TMT_API_ENDPOINT=$${SANAD_TMT_API_ENDPOINT:?Set SANAD_TMT_API_ENDPOINT} python scripts/smoke_tmt_provider.py

smoke-tmt-directions:
	cd apps/api && source .venv/bin/activate && SANAD_TMT_API_ENDPOINT=$${SANAD_TMT_API_ENDPOINT:-https://tmt.ilprl.ku.edu.np} python scripts/smoke_tmt_direction_matrix.py

validate-tamang-proof:
	cd apps/api && source .venv/bin/activate && SANAD_TMT_API_ENDPOINT=$${SANAD_TMT_API_ENDPOINT:-https://tmt.ilprl.ku.edu.np} python scripts/validate_tamang_proof_flow.py

validate-language-coverage:
	cd apps/api && source .venv/bin/activate && python scripts/validate_language_coverage.py

docker-up:
	docker compose up --build

docker-down:
	docker compose down
