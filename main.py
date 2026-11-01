
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from collections import Counter
import json
import math
import os
import re
import secrets
import sqlite3

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "shopsense.db"

STATIC_DIR.mkdir(parents=True, exist_ok=True)

ADMIN_TOKEN = os.getenv(
    "SHOPSENSE_ADMIN_TOKEN",
    "shopsense-local-admin-token"
)

APP_VERSION = "3.2.0"


# =========================================================
# SAMPLE PRODUCTS
# =========================================================

SAMPLE_PRODUCTS = [
    {
        "name": "Laptop",
        "category": "Electronics",
        "price": 750,
        "description": "Laptop for study and programming"
    },
    {
        "name": "Headphones",
        "category": "Electronics",
        "price": 50,
        "description": "Headphones for music and online classes"
    },
    {
        "name": "Backpack",
        "category": "Accessories",
        "price": 30,
        "description": "Backpack for university students"
    },
    {
        "name": "Wireless Mouse",
        "category": "Electronics",
        "price": 20,
        "description": "Wireless mouse for laptops and computers"
    },
    {
        "name": "Notebook Set",
        "category": "Stationery",
        "price": 12,
        "description": "Notebooks for school and university"
    },
    {
        "name": "Desk Lamp",
        "category": "Home",
        "price": 25,
        "description": "Desk lamp for studying and reading"
    }
]


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def get_connection():
    """
    Open a SQLite connection and always close it.

    Successful operations are committed.
    Failed operations are rolled back.
    """

    connection = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    try:
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def initialize_database():
    with get_connection() as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                description TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total REAL NOT NULL CHECK(total >= 0),
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                event_type TEXT NOT NULL
                    CHECK(event_type IN (
                        'view', 'favourite', 'cart', 'purchase'
                    )),
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(product_id)
                    REFERENCES products(id)
                    ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_interactions_product_event
            ON interactions(product_id, event_type)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_interactions_session
            ON interactions(session_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_interactions_session_id
            ON interactions(session_id, id)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                source TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_category
            ON knowledge_documents(category)
        """)

        count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        # Seed products only when the catalogue is empty.
        # Existing database records are preserved.
        if count == 0:
            connection.executemany("""
                INSERT INTO products
                    (name, category, price, description)
                VALUES (:name, :category, :price, :description)
            """, SAMPLE_PRODUCTS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


# =========================================================
# FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title="ShopSense AI",
    description=(
        "AI-powered e-commerce platform with hybrid product "
        "recommendations, interaction tracking, product comparison, "
        "grounded customer assistance and order management."
    ),
    version=APP_VERSION,
    lifespan=lifespan
)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static"
)


# =========================================================
# DATA MODELS
# =========================================================

class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    price: float = Field(ge=0, allow_inf_nan=False)
    description: str = Field(min_length=1, max_length=2000)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    description: str | None = Field(default=None, min_length=1, max_length=2000)


class RecommendationRequest(BaseModel):
    query: str | None = Field(default=None, max_length=300)
    budget: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    category: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=5, ge=1, le=20)
    session_id: str | None = Field(default=None, max_length=100)


class OrderItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=100)


class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    items: list[OrderItem] = Field(min_length=1, max_length=50)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)


class OrderStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=30)


class InteractionCreate(BaseModel):
    product_id: int = Field(gt=0)
    event_type: str = Field(pattern="^(view|favourite|cart)$")
    session_id: str = Field(min_length=1, max_length=100)


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=10, max_length=10000)
    category: str = Field(default="general", max_length=80)
    source: str = Field(default="admin", max_length=200)


class AssistantRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    session_id: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=3, ge=1, le=10)


# =========================================================
# ADMIN AUTHENTICATION
# =========================================================

def require_admin(
    x_admin_token: str | None = Header(default=None)
):
    if not x_admin_token or not secrets.compare_digest(
        x_admin_token,
        ADMIN_TOKEN
    ):
        raise HTTPException(
            status_code=401,
            detail="Valid admin token required."
        )


# =========================================================
# GENERAL HELPERS
# =========================================================

def get_product_or_404(product_id: int):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found."
        )

    return dict(row)


def tokenize(text: str):
    """
    Tokenize English letters and numbers.
    The current product catalogue and evaluation questions
    are written in English.
    """

    return re.findall(
        r"[a-zA-Z0-9]+",
        (text or "").lower()
    )


def cosine_similarity(text_a: str, text_b: str):
    """
    Transparent lexical cosine similarity.

    This is a bag-of-words retrieval method,
    not a trained neural embedding model.
    """

    words_a = Counter(tokenize(text_a))
    words_b = Counter(tokenize(text_b))

    if not words_a or not words_b:
        return 0.0

    common = set(words_a) & set(words_b)

    dot_product = sum(
        words_a[word] * words_b[word]
        for word in common
    )

    norm_a = math.sqrt(
        sum(value ** 2 for value in words_a.values())
    )

    norm_b = math.sqrt(
        sum(value ** 2 for value in words_b.values())
    )

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def normalize_scores(values):
    if not values:
        return {}

    maximum = max(values.values())

    if maximum <= 0:
        return {
            key: 0.0
            for key in values
        }

    return {
        key: value / maximum
        for key, value in values.items()
    }


def get_all_products():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM products ORDER BY id"
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def query_products(
    search=None,
    category=None,
    max_price=None,
    sort="price_asc",
    page=1,
    page_size=10
):
    sort_options = {
        "price_asc": "price ASC, id ASC",
        "price_desc": "price DESC, id ASC",
        "name_asc": "name COLLATE NOCASE ASC, id ASC"
    }

    if sort not in sort_options:
        raise HTTPException(
            status_code=400,
            detail="Invalid sorting option."
        )

    conditions = []
    parameters = []

    if search and search.strip():
        conditions.append(
            "(LOWER(name) LIKE ? OR LOWER(category) LIKE ? "
            "OR LOWER(description) LIKE ?)"
        )

        keyword = f"%{search.strip().lower()}%"
        parameters.extend([
            keyword,
            keyword,
            keyword
        ])

    if category and category.strip():
        conditions.append("LOWER(category) = ?")
        parameters.append(category.strip().lower())

    if max_price is not None:
        conditions.append("price <= ?")
        parameters.append(max_price)

    where_clause = (
        " WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    with get_connection() as connection:

        total = connection.execute(
            "SELECT COUNT(*) FROM products" + where_clause,
            parameters
        ).fetchone()[0]

        rows = connection.execute(
            "SELECT * FROM products"
            + where_clause
            + " ORDER BY " + sort_options[sort]
            + " LIMIT ? OFFSET ?",
            parameters + [
                page_size,
                (page - 1) * page_size
            ]
        ).fetchall()

        categories = connection.execute("""
            SELECT DISTINCT category
            FROM products
            ORDER BY category COLLATE NOCASE
        """).fetchall()

    return {
        "total_results": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (
            (total + page_size - 1) // page_size
            if total else 0
        ),
        "categories": [
            row["category"]
            for row in categories
        ],
        "products": [
            dict(row)
            for row in rows
        ]
    }


# =========================================================
# HOME AND HEALTH
# =========================================================

@app.get("/")
def home():
    index_file = STATIC_DIR / "index.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Frontend index.html was not found."
        )

    return FileResponse(index_file)


@app.get("/health")
def health_check():
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1")

        return {
            "status": "healthy",
            "database": "connected",
            "application": "ShopSense AI",
            "version": APP_VERSION
        }

    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed."
        )


@app.get("/system/info")
def system_info():
    return {
        "application": "ShopSense AI",
        "version": APP_VERSION,
        "features": [
            "Product catalogue",
            "Search and filtering",
            "Product comparison",
            "Interaction tracking",
            "Popularity recommendations",
            "Hybrid recommendations",
            "Recommendation evaluation",
            "Grounded customer assistant",
            "Knowledge base management",
            "Order management"
        ]
    }


# =========================================================
# PRODUCT SEARCH AND FILTERING
# =========================================================

@app.get("/products")
def get_products(
    search: str | None = Query(default=None, min_length=1),
    category: str | None = None,
    max_price: float | None = Query(default=None, ge=0),
    sort: str = "price_asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100)
):
    return query_products(
        search=search,
        category=category,
        max_price=max_price,
        sort=sort,
        page=page,
        page_size=page_size
    )


@app.get("/products/search")
def search_products(
    name: str = Query(min_length=1)
):
    return query_products(search=name)


@app.get("/products/under-price")
def get_products_under_price(
    max_price: float = Query(ge=0)
):
    return query_products(max_price=max_price)


@app.get("/products/category/{category_name}")
def get_products_by_category(category_name: str):
    return query_products(category=category_name)


@app.get("/products/sort-by-price")
def sort_products_by_price():
    return query_products(sort="price_asc")


@app.get("/products/sort-by-price-desc")
def sort_products_by_price_desc():
    return query_products(sort="price_desc")


# =========================================================
# PRODUCT COMPARISON
# Keep this route before /products/{product_id}.
# =========================================================

@app.get("/products/compare")
def compare_products(
    ids: list[int] = Query(...)
):
    if len(ids) < 2 or len(ids) > 4:
        raise HTTPException(
            status_code=422,
            detail="Compare between 2 and 4 products."
        )

    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=400,
            detail="Please provide different product IDs."
        )

    placeholders = ",".join("?" for _ in ids)

    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})",
            ids
        ).fetchall()

    found = {
        row["id"]: dict(row)
        for row in rows
    }

    missing = [
        product_id
        for product_id in ids
        if product_id not in found
    ]

    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Products not found: {missing}"
        )

    return {
        "total_results": len(ids),
        "products": [
            found[product_id]
            for product_id in ids
        ]
    }


# =========================================================
# CUSTOMER INTERACTION TRACKING
# =========================================================

@app.post("/interactions")
def record_interaction(event: InteractionCreate):
    get_product_or_404(event.product_id)

    with get_connection() as connection:
        cursor = connection.execute("""
            INSERT INTO interactions
                (product_id, event_type, session_id)
            VALUES (?, ?, ?)
        """, (
            event.product_id,
            event.event_type,
            event.session_id
        ))

        interaction_id = cursor.lastrowid

    return {
        "message": "Interaction recorded successfully.",
        "interaction_id": interaction_id,
        "product_id": event.product_id,
        "event_type": event.event_type,
        "session_id": event.session_id
    }


@app.get(
    "/admin/interactions",
    dependencies=[Depends(require_admin)]
)
def list_interactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    event_type: str | None = Query(
        default=None,
        pattern="^(view|favourite|cart|purchase)$"
    )
):
    where_clause = (
        " WHERE event_type = ?"
        if event_type else ""
    )

    parameters = (
        [event_type]
        if event_type else []
    )

    with get_connection() as connection:

        total = connection.execute(
            "SELECT COUNT(*) FROM interactions" + where_clause,
            parameters
        ).fetchone()[0]

        rows = connection.execute(
            "SELECT * FROM interactions"
            + where_clause
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            parameters + [
                page_size,
                (page - 1) * page_size
            ]
        ).fetchall()

    return {
        "total_results": total,
        "page": page,
        "page_size": page_size,
        "interactions": [
            dict(row)
            for row in rows
        ]
    }


# =========================================================
# RECOMMENDATION ENGINE
# =========================================================

EVENT_WEIGHTS = {
    "view": 1.0,
    "favourite": 3.0,
    "cart": 4.0,
    "purchase": 5.0
}


def get_popularity_scores():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT
                p.id,
                COALESCE(
                    SUM(
                        CASE i.event_type
                            WHEN 'view' THEN 1
                            WHEN 'favourite' THEN 3
                            WHEN 'cart' THEN 4
                            WHEN 'purchase' THEN 5
                            ELSE 0
                        END
                    ),
                    0
                ) AS popularity_score
            FROM products p
            LEFT JOIN interactions i
                ON i.product_id = p.id
            GROUP BY p.id
        """).fetchall()

    return {
        row["id"]: float(row["popularity_score"])
        for row in rows
    }


def get_session_profile(session_id):
    if not session_id:
        return []

    with get_connection() as connection:
        rows = connection.execute("""
            SELECT p.*, i.event_type
            FROM interactions i
            JOIN products p ON p.id = i.product_id
            WHERE i.session_id = ?
            ORDER BY i.id DESC
        """, (session_id,)).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def build_user_profile(interactions):
    profile_parts = []

    for item in interactions:
        weight = EVENT_WEIGHTS.get(
            item["event_type"],
            1.0
        )

        text_value = (
            str(item["name"]) + " "
            + str(item["category"]) + " "
            + str(item["description"])
        )

        profile_parts.extend(
            [text_value] * int(weight)
        )

    return " ".join(profile_parts)


def calculate_hybrid_recommendations(
    request,
    products=None,
    interactions=None,
    popularity_scores=None
):
    if products is None:
        products = get_all_products()

    if interactions is None:
        interactions = get_session_profile(
            request.session_id
        )

    if popularity_scores is None:
        popularity_scores = get_popularity_scores()

    user_profile = build_user_profile(interactions)

    normalized_popularity = normalize_scores(
        popularity_scores
    )

    query_text = request.query or ""

    category_filter = (
        request.category or ""
    ).strip().lower()

    # Define weights before the loop.
    # This prevents an error when no candidates match.
    if user_profile:
        content_weight = 0.65
        popularity_weight = 0.35
    else:
        content_weight = 0.80
        popularity_weight = 0.20

    candidates = []

    for product in products:

        if (
            request.budget is not None
            and product["price"] > request.budget
        ):
            continue

        if (
            category_filter
            and product["category"].strip().lower()
            != category_filter
        ):
            continue

        product_text = (
            product["name"] + " "
            + product["category"] + " "
            + product["description"]
        )

        query_similarity = cosine_similarity(
            query_text,
            product_text
        )

        profile_similarity = cosine_similarity(
            user_profile,
            product_text
        )

        content_score = max(
            query_similarity,
            profile_similarity
        )

        popularity_score = normalized_popularity.get(
            product["id"],
            0.0
        )

        hybrid_score = (
            content_weight * content_score
            + popularity_weight * popularity_score
        )

        if user_profile and content_score > 0:
            reason = (
                "Matches your previous product interactions "
                "and product popularity."
            )

        elif query_similarity > 0:
            reason = (
                "Matches your search and product information."
            )

        else:
            reason = (
                "Recommended using product popularity."
            )

        candidates.append({
            **product,
            "content_score": round(content_score, 4),
            "popularity_score": round(popularity_score, 4),
            "hybrid_score": round(hybrid_score, 4),
            "reason": reason
        })

    candidates.sort(
        key=lambda item: (
            -item["hybrid_score"],
            item["price"],
            item["id"]
        )
    )

    return {
        "method": "hybrid_recommendation",
        "weights": {
            "content": content_weight,
            "popularity": popularity_weight
        },
        "session_id": request.session_id,
        "total_results": len(candidates),
        "recommendations": candidates[:request.limit]
    }


@app.post("/recommend/hybrid")
def hybrid_recommendations(
    request: RecommendationRequest
):
    return calculate_hybrid_recommendations(request)


@app.post("/recommend")
def recommend_products(
    request: RecommendationRequest
):
    return calculate_hybrid_recommendations(request)


# =========================================================
# POPULARITY BASELINE
# =========================================================

@app.get("/recommend/popular")
def popular_products(
    limit: int = Query(default=5, ge=1, le=20)
):
    scores = get_popularity_scores()
    products = get_all_products()

    products.sort(
        key=lambda product: (
            -scores.get(product["id"], 0),
            product["id"]
        )
    )

    for product in products:
        product["popularity_score"] = scores.get(
            product["id"],
            0.0
        )

    return {
        "method": "popularity_baseline",
        "total_results": len(products),
        "recommendations": products[:limit]
    }


# =========================================================
# RECOMMENDATION EVALUATION
# Hybrid vs Popularity Baseline
# =========================================================

def precision_at_k(recommended_ids, relevant_ids, k=5):
    if k <= 0:
        return 0.0

    selected = recommended_ids[:k]

    hits = sum(
        1 for product_id in selected
        if product_id in relevant_ids
    )

    return hits / k


def dcg_at_k(recommended_ids, relevant_ids, k=5):
    score = 0.0

    for index, product_id in enumerate(
        recommended_ids[:k]
    ):
        if product_id in relevant_ids:
            score += 1 / math.log2(index + 2)

    return score


def ndcg_at_k(recommended_ids, relevant_ids, k=5):
    ideal_hits = min(len(relevant_ids), k)

    if ideal_hits == 0:
        return 0.0

    ideal_score = sum(
        1 / math.log2(index + 2)
        for index in range(ideal_hits)
    )

    if ideal_score == 0:
        return 0.0

    return (
        dcg_at_k(recommended_ids, relevant_ids, k)
        / ideal_score
    )


@app.get("/recommend/evaluate")
def evaluate_recommendations(
    k: int = Query(default=5, ge=1, le=20)
):
    """
    Session-based holdout evaluation.

    The final positive interaction for a previously unseen
    positive product is held out as the test target.

    Training interactions are used to build the profile
    and calculate popularity scores.

    Test interaction data is not used for training scores.
    """

    products = get_all_products()

    with get_connection() as connection:

        session_rows = connection.execute("""
            SELECT DISTINCT session_id
            FROM interactions
            WHERE session_id IS NOT NULL
              AND session_id != ''
        """).fetchall()

        all_interactions = connection.execute("""
            SELECT
                i.id,
                i.product_id,
                i.event_type,
                i.session_id,
                p.name,
                p.category,
                p.description,
                p.price
            FROM interactions i
            JOIN products p
                ON p.id = i.product_id
            ORDER BY i.id ASC
        """).fetchall()

    if not all_interactions:
        return {
            "status": "insufficient_data",
            "message": "No interaction data is available.",
            "sessions_evaluated": 0,
            "hybrid": None,
            "popularity_baseline": None
        }

    interactions_by_session = {}

    for row in all_interactions:
        item = dict(row)

        interactions_by_session.setdefault(
            item["session_id"],
            []
        ).append(item)

    hybrid_precision = []
    hybrid_ndcg = []

    popularity_precision = []
    popularity_ndcg = []

    evaluated_sessions = 0

    positive_events = {
        "favourite",
        "cart",
        "purchase"
    }

    for session_row in session_rows:

        session_id = session_row["session_id"]

        history = interactions_by_session.get(
            session_id,
            []
        )

        positive_history = [
            item for item in history
            if item["event_type"] in positive_events
        ]

        distinct_positive_products = set(
            item["product_id"]
            for item in positive_history
        )

        if len(distinct_positive_products) < 2:
            continue

        # Find the most recent positive interaction whose
        # product has not appeared in an earlier positive event.
        # This prevents the target product from leaking into training.
        test_interaction = None

        seen_positive_products = set()

        for item in reversed(positive_history):

            product_id = item["product_id"]

            if product_id not in seen_positive_products:
                test_interaction = item
                break

            seen_positive_products.add(product_id)

        if test_interaction is None:
            continue

        test_product_id = test_interaction["product_id"]

        training_history = [
            item for item in history
            if item["id"] < test_interaction["id"]
        ]

        training_positive_ids = set(
            item["product_id"]
            for item in training_history
            if item["event_type"] in positive_events
        )

        # The target must not already exist in training.
        if test_product_id in training_positive_ids:
            continue

        candidate_products = [
            product for product in products
            if product["id"] not in training_positive_ids
        ]

        if not candidate_products:
            continue

        # Popularity scores from training data only.
        training_popularity = {
            product["id"]: 0.0
            for product in products
        }

        for item in training_history:

            weight = EVENT_WEIGHTS.get(
                item["event_type"],
                0.0
            )

            training_popularity[item["product_id"]] += weight

        normalized_training_popularity = normalize_scores(
            training_popularity
        )

        # Build user profile from training history.
        profile_parts = []

        for item in training_history:

            weight = EVENT_WEIGHTS.get(
                item["event_type"],
                1.0
            )

            text_value = (
                item["name"] + " "
                + item["category"] + " "
                + item["description"]
            )

            profile_parts.extend(
                [text_value] * int(weight)
            )

        profile_text = " ".join(profile_parts)

        # Hybrid scores.
        hybrid_scores = []

        for product in candidate_products:

            product_text = (
                product["name"] + " "
                + product["category"] + " "
                + product["description"]
            )

            content_score = cosine_similarity(
                profile_text,
                product_text
            )

            popularity_score = (
                normalized_training_popularity.get(
                    product["id"],
                    0.0
                )
            )

            score = (
                0.65 * content_score
                + 0.35 * popularity_score
            )

            hybrid_scores.append((
                product["id"],
                score
            ))

        hybrid_scores.sort(
            key=lambda item: (
                -item[1],
                item[0]
            )
        )

        hybrid_ids = [
            item[0]
            for item in hybrid_scores[:k]
        ]

        # Popularity baseline.
        baseline_scores = [
            (
                product["id"],
                normalized_training_popularity.get(
                    product["id"],
                    0.0
                )
            )
            for product in candidate_products
        ]

        baseline_scores.sort(
            key=lambda item: (
                -item[1],
                item[0]
            )
        )

        baseline_ids = [
            item[0]
            for item in baseline_scores[:k]
        ]

        relevant_ids = {
            test_product_id
        }

        hybrid_precision.append(
            precision_at_k(
                hybrid_ids,
                relevant_ids,
                k
            )
        )

        hybrid_ndcg.append(
            ndcg_at_k(
                hybrid_ids,
                relevant_ids,
                k
            )
        )

        popularity_precision.append(
            precision_at_k(
                baseline_ids,
                relevant_ids,
                k
            )
        )

        popularity_ndcg.append(
            ndcg_at_k(
                baseline_ids,
                relevant_ids,
                k
            )
        )

        evaluated_sessions += 1

    if evaluated_sessions == 0:
        return {
            "status": "insufficient_data",
            "message": (
                "At least two distinct positive products per session "
                "are required. A positive product used as the test "
                "target must not have an earlier positive interaction "
                "in the same session."
            ),
            "sessions_evaluated": 0,
            "hybrid": None,
            "popularity_baseline": None
        }

    return {
        "status": "completed",
        "evaluation_method": "session_based_holdout",
        "k": k,
        "sessions_evaluated": evaluated_sessions,
        "hybrid": {
            "precision_at_k": round(
                sum(hybrid_precision) / evaluated_sessions,
                4
            ),
            "ndcg_at_k": round(
                sum(hybrid_ndcg) / evaluated_sessions,
                4
            )
        },
        "popularity_baseline": {
            "precision_at_k": round(
                sum(popularity_precision) / evaluated_sessions,
                4
            ),
            "ndcg_at_k": round(
                sum(popularity_ndcg) / evaluated_sessions,
                4
            )
        },
        "note": (
            "Evaluation uses recorded interactions and a "
            "session-based holdout method. Results are not reliable "
            "until sufficient real user interaction data has "
            "been collected."
        )
    }


# =========================================================
# KNOWLEDGE BASE
# =========================================================

def get_knowledge_documents():

    with get_connection() as connection:

        documents = connection.execute("""
            SELECT id, title, content, category, source
            FROM knowledge_documents
            ORDER BY id DESC
        """).fetchall()

        products = connection.execute(
            "SELECT * FROM products"
        ).fetchall()

    result = [
        dict(row)
        for row in documents
    ]

    # Product catalogue is also available as grounded knowledge.
    for product_row in products:

        product = dict(product_row)

        result.append({
            "id": f"product-{product['id']}",
            "title": product["name"],
            "content": (
                f"Product: {product['name']}. "
                f"Category: {product['category']}. "
                f"Price: ${product['price']:.2f}. "
                f"Description: {product['description']}."
            ),
            "category": "product",
            "source": (
                f"Product catalogue, product ID {product['id']}"
            )
        })

    return result


def retrieve_knowledge(question, limit=3):

    documents = get_knowledge_documents()

    ranked = []

    question_tokens = set(tokenize(question))

    if not question_tokens:
        return []

    for document in documents:

        document_text = (
            document["title"] + " " + document["content"]
        )

        similarity = cosine_similarity(
            question,
            document_text
        )

        if similarity > 0:
            ranked.append({
                **document,
                "similarity": round(similarity, 4)
            })

    ranked.sort(
        key=lambda item: (
            -item["similarity"],
            str(item["title"]).lower()
        )
    )

    return ranked[:limit]


# =========================================================
# KNOWLEDGE BASE ADMIN ROUTES
# =========================================================

@app.post(
    "/admin/knowledge",
    dependencies=[Depends(require_admin)]
)
def add_knowledge_document(document: KnowledgeCreate):

    with get_connection() as connection:

        cursor = connection.execute("""
            INSERT INTO knowledge_documents
                (title, content, category, source)
            VALUES (?, ?, ?, ?)
        """, (
            document.title.strip(),
            document.content.strip(),
            document.category.strip() or "general",
            document.source.strip() or "admin"
        ))

        document_id = cursor.lastrowid

    return {
        "message": "Knowledge document added successfully.",
        "document_id": document_id,
        "title": document.title
    }


@app.get(
    "/admin/knowledge",
    dependencies=[Depends(require_admin)]
)
def list_knowledge_documents():

    with get_connection() as connection:

        rows = connection.execute("""
            SELECT * FROM knowledge_documents
            ORDER BY id DESC
        """).fetchall()

    return {
        "total_results": len(rows),
        "documents": [
            dict(row)
            for row in rows
        ]
    }


@app.delete(
    "/admin/knowledge/{document_id}",
    dependencies=[Depends(require_admin)]
)
def delete_knowledge_document(document_id: int):

    with get_connection() as connection:

        cursor = connection.execute(
            "DELETE FROM knowledge_documents WHERE id = ?",
            (document_id,)
        )

        deleted = cursor.rowcount

    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail="Knowledge document not found."
        )

    return {
        "message": "Knowledge document deleted.",
        "document_id": document_id
    }


# =========================================================
# GROUNDED CUSTOMER ASSISTANT
# =========================================================

@app.post("/assistant/chat")
def assistant_chat(request: AssistantRequest):
    """
    Retrieval-based grounded assistant.

    It uses product catalogue data and admin knowledge documents.
    It does not invent policies that are absent from the knowledge base.
    """

    retrieved = retrieve_knowledge(
        request.question,
        request.limit
    )

    # Conservative lexical relevance threshold.
    relevant = [
        document for document in retrieved
        if document["similarity"] >= 0.12
    ]

    if not relevant:

        return {
            "answer": (
                "I could not find enough information in the "
                "available ShopSense knowledge base to answer "
                "this question reliably. Please contact the "
                "store administrator or provide the relevant "
                "product or policy information."
            ),
            "grounded": False,
            "abstained": True,
            "sources": [],
            "citations": []
        }

    answer_parts = [
        document["content"]
        for document in relevant
    ]

    answer = " ".join(answer_parts)

    sources = [
        {
            "id": document["id"],
            "title": document["title"],
            "category": document["category"],
            "source": document["source"],
            "similarity": document["similarity"]
        }
        for document in relevant
    ]

    return {
        "answer": answer,
        "grounded": True,
        "abstained": False,
        "method": "retrieval_based_extractive_answer",
        "sources": sources,
        "citations": sources,
        "disclaimer": (
            "The answer is assembled from retrieved knowledge "
            "documents. Verify important policies with the store."
        )
    }


@app.get("/assistant/knowledge")
def public_knowledge_categories():

    with get_connection() as connection:

        rows = connection.execute("""
            SELECT category, COUNT(*) AS document_count
            FROM knowledge_documents
            GROUP BY category
        """).fetchall()

    return {
        "categories": [
            dict(row)
            for row in rows
        ],
        "note": (
            "Product catalogue entries are also available "
            "to the assistant as knowledge."
        )
    }


# =========================================================
# RAG EVALUATION QUESTION SET
# =========================================================

@app.get("/assistant/evaluation-questions")
def assistant_evaluation_questions():

    questions = [
        "What is the price of the Laptop?",
        "What category does the Laptop belong to?",
        "What is the Laptop used for?",
        "What is the price of the Headphones?",
        "What category do the Headphones belong to?",
        "What are the Headphones designed for?",
        "What is the price of the Backpack?",
        "What category does the Backpack belong to?",
        "What is the Backpack designed for?",
        "What is the price of the Wireless Mouse?",
        "What category does the Wireless Mouse belong to?",
        "What is the Wireless Mouse used for?",
        "What is the price of the Notebook Set?",
        "What category does the Notebook Set belong to?",
        "What are the notebooks designed for?",
        "What is the price of the Desk Lamp?",
        "What category does the Desk Lamp belong to?",
        "What is the Desk Lamp used for?",
        "Which product costs 750 dollars?",
        "Which product costs 50 dollars?",
        "Which product costs 30 dollars?",
        "Which product costs 20 dollars?",
        "Which product costs 12 dollars?",
        "Which product costs 25 dollars?",
        "Which products belong to Electronics?",
        "Which product belongs to Accessories?",
        "Which product belongs to Stationery?",
        "Which product belongs to Home?",
        "Which product is designed for programming?",
        "Which product is designed for online classes?",
        "Which product is suitable for university students?",
        "Which product is related to reading?",
        "Is the Laptop more expensive than the Backpack?",
        "Is the Desk Lamp cheaper than the Headphones?",
        "Which listed product has the lowest price?",
        "Which listed product has the highest price?",
        "Does the catalogue contain a Wireless Mouse?",
        "Does the catalogue contain a Desk Lamp?",
        "What is the description of the Backpack?",
        "What is the description of the Notebook Set?",
        "What is the delivery fee?",
        "How many days does delivery take?",
        "What is the return policy?",
        "Can I return a purchased product?",
        "What payment methods are accepted?",
        "Is cash on delivery available?",
        "What is the size guide?",
        "How can I contact customer support?",
        "What is the warranty period?",
        "Can you tell me something not included in the catalogue?"
    ]

    return {
        "total_questions": len(questions),
        "questions": [
            {
                "id": index + 1,
                "question": question
            }
            for index, question in enumerate(questions)
        ],
        "note": (
            "These are evaluation prompts, not measured results. "
            "Questions about policies absent from the knowledge base "
            "should receive an abstention."
        )
    }


# =========================================================
# ADMIN PRODUCT MANAGEMENT
# =========================================================

@app.post(
    "/products",
    dependencies=[Depends(require_admin)]
)
def create_product(product: ProductCreate):

    with get_connection() as connection:

        cursor = connection.execute("""
            INSERT INTO products
                (name, category, price, description)
            VALUES (?, ?, ?, ?)
        """, (
            product.name.strip(),
            product.category.strip(),
            product.price,
            product.description.strip()
        ))

        product_id = cursor.lastrowid

    return get_product_or_404(product_id)


@app.put(
    "/products/{product_id}",
    dependencies=[Depends(require_admin)]
)
def update_product(
    product_id: int,
    product: ProductUpdate
):

    changes = product.model_dump(
        exclude_unset=True
    )

    if not changes:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one field to update."
        )

    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=422,
            detail="Product fields cannot be null."
        )

    get_product_or_404(product_id)

    allowed_fields = {
        "name",
        "category",
        "price",
        "description"
    }

    if not set(changes).issubset(allowed_fields):
        raise HTTPException(
            status_code=400,
            detail="Invalid product field."
        )

    # Normalize text values before saving.
    for field in ("name", "category", "description"):
        if field in changes:
            changes[field] = changes[field].strip()

            if not changes[field]:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} cannot be empty."
                )

    assignments = ", ".join(
        f"{key} = ?"
        for key in changes
    )

    values = list(changes.values()) + [
        product_id
    ]

    with get_connection() as connection:

        connection.execute(
            f"UPDATE products SET {assignments} WHERE id = ?",
            values
        )

    return get_product_or_404(product_id)


@app.delete(
    "/products/{product_id}",
    dependencies=[Depends(require_admin)]
)
def delete_product(product_id: int):

    with get_connection() as connection:

        cursor = connection.execute(
            "DELETE FROM products WHERE id = ?",
            (product_id,)
        )

        deleted = cursor.rowcount

    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail="Product not found."
        )

    return {
        "message": "Product deleted successfully.",
        "product_id": product_id
    }


# =========================================================
# PRODUCT DETAILS
# Keep this dynamic route after static product routes.
# =========================================================

@app.get("/products/{product_id}")
def get_product(product_id: int):
    return get_product_or_404(product_id)


# =========================================================
# ORDERS AND DEMONSTRATION CHECKOUT
# =========================================================

@app.post("/orders")
def create_order(order: OrderCreate):

    customer_name = order.customer_name.strip()

    if not customer_name:
        raise HTTPException(
            status_code=422,
            detail="Customer name cannot be empty."
        )

    quantities = {}

    for item in order.items:

        quantities[item.product_id] = (
            quantities.get(item.product_id, 0)
            + item.quantity
        )

    # Prevent excessive quantities after duplicate items are combined.
    if any(quantity > 100 for quantity in quantities.values()):
        raise HTTPException(
            status_code=422,
            detail="The maximum quantity per product is 100."
        )

    product_ids = list(quantities.keys())

    placeholders = ",".join(
        "?" for _ in product_ids
    )

    with get_connection() as connection:

        rows = connection.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})",
            product_ids
        ).fetchall()

        products = {
            row["id"]: dict(row)
            for row in rows
        }

        missing = [
            product_id
            for product_id in product_ids
            if product_id not in products
        ]

        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Products not found: {missing}"
            )

        order_items = []
        total = 0.0

        for product_id, quantity in quantities.items():

            product = products[product_id]

            subtotal = round(
                product["price"] * quantity,
                2
            )

            total += subtotal

            order_items.append({
                "product_id": product_id,
                "name": product["name"],
                "unit_price": product["price"],
                "quantity": quantity,
                "subtotal": subtotal
            })

        total = round(total, 2)

        cursor = connection.execute("""
            INSERT INTO orders
                (customer_name, items_json, total, status)
            VALUES (?, ?, ?, 'pending')
        """, (
            customer_name,
            json.dumps(order_items),
            total
        ))

        order_id = cursor.lastrowid

        purchase_session = (
            order.session_id or f"order-{order_id}"
        )

        for product_id, quantity in quantities.items():

            for _ in range(quantity):

                connection.execute("""
                    INSERT INTO interactions
                        (product_id, event_type, session_id)
                    VALUES (?, 'purchase', ?)
                """, (
                    product_id,
                    purchase_session
                ))

        created = connection.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        result = dict(created)

    return {
        "id": result["id"],
        "customer_name": result["customer_name"],
        "items": order_items,
        "total": result["total"],
        "status": result["status"],
        "created_at": result["created_at"],
        "message": (
            "Demo order created. No payment was processed."
        )
    }


@app.get(
    "/admin/orders",
    dependencies=[Depends(require_admin)]
)
def list_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100)
):

    with get_connection() as connection:

        total = connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        rows = connection.execute("""
            SELECT * FROM orders
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (
            page_size,
            (page - 1) * page_size
        )).fetchall()

    orders = []

    for row in rows:

        order = dict(row)

        try:
            order["items"] = json.loads(
                order.pop("items_json")
            )

        except (json.JSONDecodeError, TypeError):
            order["items"] = []

        orders.append(order)

    return {
        "total_results": total,
        "page": page,
        "page_size": page_size,
        "orders": orders
    }


@app.patch(
    "/admin/orders/{order_id}",
    dependencies=[Depends(require_admin)]
)
def update_order_status(
    order_id: int,
    update: OrderStatusUpdate
):

    allowed_statuses = {
        "pending",
        "confirmed",
        "shipped",
        "completed",
        "cancelled"
    }

    new_status = update.status.strip().lower()

    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail=(
                "Status must be one of: "
                + ", ".join(sorted(allowed_statuses))
            )
        )

    with get_connection() as connection:

        cursor = connection.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (new_status, order_id)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Order not found."
            )

        row = connection.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        result = dict(row)

    try:
        result["items"] = json.loads(
            result.pop("items_json")
        )

    except (json.JSONDecodeError, TypeError):
        result["items"] = []

    return result


# =========================================================
# ADMIN DASHBOARD SUMMARY
# =========================================================

@app.get(
    "/admin/dashboard",
    dependencies=[Depends(require_admin)]
)
def admin_dashboard():

    with get_connection() as connection:

        product_count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        order_count = connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        interaction_count = connection.execute(
            "SELECT COUNT(*) FROM interactions"
        ).fetchone()[0]

        knowledge_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_documents"
        ).fetchone()[0]

        revenue = connection.execute("""
            SELECT COALESCE(SUM(total), 0)
            FROM orders
            WHERE status != 'cancelled'
        """).fetchone()[0]

        order_statuses = connection.execute("""
            SELECT status, COUNT(*) AS count
            FROM orders
            GROUP BY status
        """).fetchall()

    return {
        "products": product_count,
        "orders": order_count,
        "interactions": interaction_count,
        "knowledge_documents": knowledge_count,
        "total_order_value": round(float(revenue), 2),
        "order_statuses": [
            dict(row)
            for row in order_statuses
        ]
    }


# =========================================================
# RUN SERVER
# =========================================================

if __name__ == "__main__":

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
