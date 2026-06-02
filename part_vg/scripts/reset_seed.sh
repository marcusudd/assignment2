#!/usr/bin/env bash
# Reset workspace to the seed FastAPI app.
# Run from part_vg/:  bash scripts/reset_seed.sh
set -euo pipefail

WORKSPACE="$(dirname "$0")/../workspace"
cd "$WORKSPACE"

echo "Resetting workspace..."

# Remove everything except .gitkeep
find . -type f -not -name ".gitkeep" -delete
find . -mindepth 1 -type d -empty -delete 2>/dev/null || true

# Recreate structure
mkdir -p models schemas routers tests

# main.py — minimal FastAPI app
cat > main.py << 'PYEOF'
from fastapi import FastAPI

app = FastAPI(title="Demo Shop API")


@app.get("/health")
def health():
    return {"status": "ok"}
PYEOF

# models/
touch models/__init__.py

cat > models/item.py << 'PYEOF'
from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"

    id    = Column(Integer, primary_key=True)
    name  = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
PYEOF

# Empty package stubs
touch schemas/__init__.py
touch routers/__init__.py
touch tests/__init__.py

echo "Done. Workspace:"
find . -type f -not -name ".gitkeep" | sort
