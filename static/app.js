
const API_URL = "/products";

const CART_STORAGE_KEY = "shopsense_cart";
const FAVOURITES_STORAGE_KEY = "shopsense_favourites";
const SESSION_KEY = "shopsense_session_id";
const VIEWED_PRODUCTS_KEY = "shopsense_viewed_products";

// ==================================================
// SESSION
// ==================================================

function getSessionId() {
    let sessionId = sessionStorage.getItem(SESSION_KEY);

    if (!sessionId) {
        sessionId =
            "user-" +
            Date.now() +
            "-" +
            Math.random().toString(36).substring(2, 10);

        sessionStorage.setItem(SESSION_KEY, sessionId);
    }

    return sessionId;
}

const sessionId = getSessionId();

// ==================================================
// HTML ELEMENTS
// ==================================================

const searchInput = document.getElementById("searchInput");
const categoryFilter = document.getElementById("categoryFilter");
const maxPriceInput = document.getElementById("maxPrice");
const searchButton = document.getElementById("searchButton");
const resetButton = document.getElementById("resetButton");
const sortFilter = document.getElementById("sortFilter");
const resultMessage = document.getElementById("resultMessage");
const productList = document.getElementById("productList");

const recommendInput = document.getElementById("recommendInput");
const recommendButton = document.getElementById("recommendButton");
const recommendMessage = document.getElementById("recommendMessage");
const recommendationList = document.getElementById("recommendationList");

const compareButton = document.getElementById("compareButton");
const clearCompareButton = document.getElementById("clearCompareButton");
const comparisonResults = document.getElementById("comparisonResults");

const cartItems = document.getElementById("cartItems");
const cartMessage = document.getElementById("cartMessage");
const placeOrderButton = document.getElementById("placeOrderButton");

const assistantForm = document.getElementById("assistantForm");
const assistantQuestion = document.getElementById("assistantQuestion");
const assistantMessages = document.getElementById("assistantMessages");
const assistantSendButton = document.getElementById("assistantSendButton");
const assistantStatus = document.getElementById("assistantStatus");

// ==================================================
// APPLICATION STATE
// ==================================================

let selectedForComparison = [];
let shoppingCart = loadSavedCart();
let currentProducts = [];
let favourites = loadFavourites();

// ==================================================
// TRANSLATION
// ==================================================

function translate(key, fallback) {
    const language =
        document.getElementById("languageSelect")?.value || "en";

    const dictionaries =
        typeof translations !== "undefined" ? translations : {};

    return (
        dictionaries[language]?.[key] ||
        dictionaries.en?.[key] ||
        fallback
    );
}

// ==================================================
// GENERAL HELPERS
// ==================================================

function createElement(tag, className = "", text = "") {
    const element = document.createElement(tag);

    if (className) {
        element.className = className;
    }

    if (text !== undefined && text !== null && text !== "") {
        element.textContent = String(text);
    }

    return element;
}

function formatPrice(price) {
    const amount = Number(price);

    return Number.isFinite(amount)
        ? `$${amount.toFixed(2)}`
        : "$0.00";
}

function setMessage(element, message) {
    if (element) {
        element.textContent = message || "";
    }
}

async function getErrorMessage(response) {
    try {
        const data = await response.json();

        if (typeof data.detail === "string") {
            return data.detail;
        }

        if (data.detail) {
            return JSON.stringify(data.detail);
        }

        if (typeof data.message === "string") {
            return data.message;
        }
    } catch (error) {
        console.error("Could not read error response:", error);
    }

    return `Request failed (${response.status})`;
}

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, options);

    if (!response.ok) {
        throw new Error(await getErrorMessage(response));
    }

    if (response.status === 204) {
        return null;
    }

    const contentType = response.headers.get("content-type") || "";

    if (!contentType.includes("application/json")) {
        throw new Error("The server returned an unexpected response.");
    }

    return response.json();
}

function getProductId(product) {
    const id = Number(product?.id);

    return Number.isInteger(id) && id > 0 ? id : null;
}

// ==================================================
// USER INTERACTION TRACKING
// ==================================================

async function recordInteraction(productId, eventType) {
    const id = Number(productId);

    if (!Number.isInteger(id) || id <= 0) {
        return;
    }

    try {
        await fetchJSON("/interactions", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                product_id: id,
                event_type: eventType,
                session_id: sessionId
            })
        });
    } catch (error) {
        console.warn(
            "Interaction tracking failed:",
            eventType,
            id,
            error.message
        );
    }
}

function recordProductView(productId) {
    const id = Number(productId);

    if (!Number.isInteger(id) || id <= 0) {
        return;
    }

    let viewedProducts = [];

    try {
        viewedProducts = JSON.parse(
            sessionStorage.getItem(VIEWED_PRODUCTS_KEY) || "[]"
        );

        if (!Array.isArray(viewedProducts)) {
            viewedProducts = [];
        }
    } catch {
        viewedProducts = [];
    }

    if (viewedProducts.includes(id)) {
        return;
    }

    viewedProducts.push(id);

    sessionStorage.setItem(
        VIEWED_PRODUCTS_KEY,
        JSON.stringify(viewedProducts)
    );

    recordInteraction(id, "view");
}

// ==================================================
// PRODUCT SEARCH AND FILTER
// ==================================================

async function loadProducts() {
    if (
        !searchInput ||
        !categoryFilter ||
        !maxPriceInput ||
        !sortFilter ||
        !productList
    ) {
        console.warn("Product search elements were not found.");
        return;
    }

    const params = new URLSearchParams();

    const search = searchInput.value.trim();
    const category = categoryFilter.value;
    const priceText = maxPriceInput.value.trim().replace(",", ".");
    const sort = sortFilter.value;

    if (search) {
        params.set("search", search);
    }

    if (category) {
        params.set("category", category);
    }

    if (priceText !== "") {
        const price = Number(priceText);

        if (!Number.isFinite(price) || price < 0) {
            setMessage(
                resultMessage,
                "Enter a valid maximum price of 0 or higher."
            );

            maxPriceInput.focus();
            return;
        }

        params.set("max_price", String(price));
    }

    if (sort) {
        params.set("sort", sort);
    }

    params.set("page", "1");
    params.set("page_size", "100");

    if (searchButton) {
        searchButton.disabled = true;
    }

    setMessage(resultMessage, "Loading products...");
    productList.replaceChildren();

    try {
        const data = await fetchJSON(
            `${API_URL}?${params.toString()}`
        );

        currentProducts = Array.isArray(data.products)
            ? data.products
            : [];

        displayProducts(currentProducts);

        const total = Number.isFinite(Number(data.total_results))
            ? Number(data.total_results)
            : currentProducts.length;

        setMessage(
            resultMessage,
            `${total} product(s) found.`
        );
    } catch (error) {
        console.error("Product loading error:", error);

        currentProducts = [];

        setMessage(
            resultMessage,
            `Could not load products: ${error.message}`
        );

        productList.replaceChildren();
    } finally {
        if (searchButton) {
            searchButton.disabled = false;
        }
    }
}

function displayProducts(products) {
    if (!productList) {
        return;
    }

    productList.replaceChildren();

    if (!Array.isArray(products) || products.length === 0) {
        productList.appendChild(
            createElement(
                "p",
                "result-message",
                "No products found."
            )
        );

        return;
    }

    products.forEach(product => {
        productList.appendChild(createProductCard(product));
    });
}

// ==================================================
// PRODUCT CARDS
// ==================================================

function createProductCard(product, options = {}) {
    const card = createElement("article", "product-card");

    if (!product || typeof product !== "object") {
        return card;
    }

    const productId = getProductId(product);

    card.append(
        createElement(
            "h3",
            "",
            product.name || "Unnamed product"
        ),
        createElement(
            "p",
            "product-category",
            product.category || "Uncategorized"
        ),
        createElement(
            "p",
            "",
            product.description || "No description available."
        ),
        createElement(
            "p",
            "product-price",
            formatPrice(product.price)
        )
    );

    if (productId) {
        recordProductView(productId);
    }

    // FAVOURITE BUTTON

    if (options.showFavourite !== false && productId) {
        const favouriteButton = createElement(
            "button",
            "secondary-button",
            favourites.includes(productId)
                ? "♥ Remove Favourite"
                : "♡ Add to Favourites"
        );

        favouriteButton.type = "button";

        favouriteButton.addEventListener("click", () => {
            toggleFavourite(product);

            favouriteButton.textContent =
                favourites.includes(productId)
                    ? "♥ Remove Favourite"
                    : "♡ Add to Favourites";
        });

        card.appendChild(favouriteButton);
    }

    // COMPARE CHECKBOX

    if (options.showCompare !== false && productId) {
        const label = createElement(
            "label",
            "product-action-label",
            translate("selectForCompare", "Select to compare")
        );

        const checkbox = document.createElement("input");

        checkbox.type = "checkbox";

        checkbox.checked = selectedForComparison.some(
            item => Number(item.id) === productId
        );

        checkbox.addEventListener("change", () => {
            const alreadySelected = selectedForComparison.some(
                item => Number(item.id) === productId
            );

            if (checkbox.checked) {
                if (alreadySelected) {
                    return;
                }

                if (selectedForComparison.length >= 4) {
                    checkbox.checked = false;

                    alert(
                        "You can compare up to 4 products at a time."
                    );

                    return;
                }

                selectedForComparison.push(product);
            } else {
                selectedForComparison =
                    selectedForComparison.filter(
                        item => Number(item.id) !== productId
                    );
            }
        });

        label.prepend(checkbox);
        card.appendChild(label);
    }

    // ADD TO CART

    if (options.showCart !== false && productId) {
        const addButton = createElement(
            "button",
            "primary-button",
            translate("addToCart", "Add to Cart")
        );

        addButton.type = "button";

        addButton.addEventListener("click", () => {
            addToCart(product);
        });

        card.appendChild(addButton);
    }

    return card;
}

// ==================================================
// FAVOURITES
// ==================================================

function loadFavourites() {
    try {
        const parsed = JSON.parse(
            localStorage.getItem(FAVOURITES_STORAGE_KEY) || "[]"
        );

        return Array.isArray(parsed)
            ? [...new Set(
                parsed
                    .map(Number)
                    .filter(id => Number.isInteger(id) && id > 0)
            )]
            : [];
    } catch (error) {
        console.warn("Could not load favourites:", error);
        return [];
    }
}

function saveFavourites() {
    try {
        localStorage.setItem(
            FAVOURITES_STORAGE_KEY,
            JSON.stringify(favourites)
        );
    } catch (error) {
        console.warn("Could not save favourites:", error);
    }
}

function toggleFavourite(product) {
    const productId = getProductId(product);

    if (!productId) {
        return;
    }

    if (favourites.includes(productId)) {
        favourites = favourites.filter(id => id !== productId);
    } else {
        favourites.push(productId);
        recordInteraction(productId, "favourite");
    }

    saveFavourites();
}

// ==================================================
// HYBRID AI RECOMMENDATIONS
// ==================================================

async function getRecommendations() {
    if (!recommendInput || !recommendationList) {
        return;
    }

    const query = recommendInput.value.trim();

    if (!query) {
        setMessage(
            recommendMessage,
            "Please describe the product you need."
        );

        recommendInput.focus();
        return;
    }

    if (recommendButton) {
        recommendButton.disabled = true;
    }

    recommendationList.replaceChildren();

    setMessage(
        recommendMessage,
        "Finding matching products..."
    );

    try {
        const data = await fetchJSON("/recommend", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                query,
                session_id: sessionId,
                limit: 5
            })
        });

        const recommendations = Array.isArray(data)
            ? data
            : (
                data.recommendations ||
                data.products ||
                []
            );

        if (!Array.isArray(recommendations) ||
            recommendations.length === 0) {
            setMessage(
                recommendMessage,
                "No matching products found. Try different keywords."
            );

            return;
        }

        recommendations.forEach(product => {
            recommendationList.appendChild(
                createProductCard(product)
            );
        });

        setMessage(
            recommendMessage,
            `${recommendations.length} recommended product(s) found.`
        );
    } catch (error) {
        console.error("Recommendation error:", error);

        setMessage(
            recommendMessage,
            `Could not get recommendations: ${error.message}`
        );
    } finally {
        if (recommendButton) {
            recommendButton.disabled = false;
        }
    }
}

// ==================================================
// PRODUCT COMPARISON
// ==================================================

async function compareSelectedProducts() {
    if (!comparisonResults) {
        return;
    }

    if (selectedForComparison.length < 2) {
        comparisonResults.replaceChildren();

        comparisonResults.appendChild(
            createElement(
                "p",
                "result-message",
                "Select at least 2 products using the checkboxes."
            )
        );

        return;
    }

    const params = new URLSearchParams();

    selectedForComparison.forEach(product => {
        params.append("ids", String(product.id));
    });

    if (compareButton) {
        compareButton.disabled = true;
    }

    comparisonResults.replaceChildren();

    try {
        const data = await fetchJSON(
            `/products/compare?${params.toString()}`
        );

        const products = Array.isArray(data)
            ? data
            : (data.products || []);

        if (!Array.isArray(products) || products.length === 0) {
            throw new Error(
                "The API returned no comparison results."
            );
        }

        products.forEach(product => {
            comparisonResults.appendChild(
                createProductCard(product, {
                    showCompare: false,
                    showCart: true
                })
            );
        });
    } catch (error) {
        console.error("Comparison error:", error);

        comparisonResults.appendChild(
            createElement(
                "p",
                "result-message",
                `Could not compare products: ${error.message}`
            )
        );
    } finally {
        if (compareButton) {
            compareButton.disabled = false;
        }
    }
}

function clearComparison() {
    selectedForComparison = [];

    if (comparisonResults) {
        comparisonResults.replaceChildren();
    }

    displayProducts(currentProducts);
}

// ==================================================
// SHOPPING CART
// ==================================================

function loadSavedCart() {
    try {
        const parsed = JSON.parse(
            localStorage.getItem(CART_STORAGE_KEY) || "[]"
        );

        if (!Array.isArray(parsed)) {
            return [];
        }

        return parsed
            .filter(item =>
                item &&
                item.product &&
                Number.isInteger(Number(item.product.id)) &&
                Number.isInteger(Number(item.quantity)) &&
                Number(item.quantity) >= 1
            )
            .map(item => ({
                product: item.product,
                quantity: Number(item.quantity)
            }));
    } catch (error) {
        console.warn("Could not restore cart:", error);
        return [];
    }
}

function saveCart() {
    try {
        localStorage.setItem(
            CART_STORAGE_KEY,
            JSON.stringify(shoppingCart)
        );
    } catch (error) {
        console.warn("Could not save cart:", error);
    }
}

function addToCart(product) {
    const productId = getProductId(product);

    if (!productId) {
        setMessage(cartMessage, "This product cannot be added to the cart.");
        return;
    }

    const existingItem = shoppingCart.find(
        item => Number(item.product.id) === productId
    );

    if (existingItem) {
        existingItem.quantity += 1;
    } else {
        shoppingCart.push({
            product,
            quantity: 1
        });
    }

    saveCart();
    renderCart();

    setMessage(
        cartMessage,
        `${product.name} added to your cart.`
    );

    recordInteraction(productId, "cart");
}

function renderCart() {
    if (!cartItems || !cartMessage) {
        return;
    }

    cartItems.replaceChildren();

    if (!shoppingCart.length) {
        setMessage(
            cartMessage,
            translate("cartEmpty", "Your cart is empty.")
        );

        if (placeOrderButton) {
            placeOrderButton.disabled = true;
        }

        return;
    }

    setMessage(cartMessage, "");

    if (placeOrderButton) {
        placeOrderButton.disabled = false;
    }

    let total = 0;

    shoppingCart.forEach(item => {
        const row = createElement("div", "cart-item");

        const price = Number(item.product.price);
        const subtotal = (
            Number.isFinite(price) ? price : 0
        ) * item.quantity;

        total += subtotal;

        row.appendChild(
            createElement(
                "p",
                "",
                `${item.product.name} × ${item.quantity} — ${formatPrice(subtotal)}`
            )
        );

        const removeButton = createElement(
            "button",
            "secondary-button",
            translate("removeFromCart", "Remove")
        );

        removeButton.type = "button";

        removeButton.addEventListener("click", () => {
            shoppingCart = shoppingCart.filter(
                cartItem =>
                    Number(cartItem.product.id) !==
                    Number(item.product.id)
            );

            saveCart();
            renderCart();
        });

        row.appendChild(removeButton);
        cartItems.appendChild(row);
    });

    cartItems.appendChild(
        createElement(
            "h3",
            "cart-total",
            `Total: ${formatPrice(total)}`
        )
    );
}

// ==================================================
// DEMO CHECKOUT
// ==================================================

async function placeDemoOrder() {
    if (!shoppingCart.length) {
        setMessage(
            cartMessage,
            "Your cart is empty. Add a product first."
        );

        return;
    }

    const customerName = prompt(
        "Enter your name for this demo order:"
    );

    if (customerName === null) {
        return;
    }

    if (!customerName.trim()) {
        setMessage(
            cartMessage,
            "Please enter your name to place the order."
        );

        return;
    }

    const orderPayload = {
        customer_name: customerName.trim(),
        session_id: sessionId,
        items: shoppingCart.map(item => ({
            product_id: Number(item.product.id),
            quantity: Number(item.quantity)
        }))
    };

    if (placeOrderButton) {
        placeOrderButton.disabled = true;
    }

    setMessage(
        cartMessage,
        "Submitting your demo order..."
    );

    try {
        const result = await fetchJSON("/orders", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(orderPayload)
        });

        shoppingCart = [];

        saveCart();
        renderCart();

        setMessage(
            cartMessage,
            `Order created successfully! Order ID: ${result.id}. Total: ${formatPrice(result.total)}. No payment was processed.`
        );
    } catch (error) {
        console.error("Order error:", error);

        setMessage(
            cartMessage,
            `Could not place the order: ${error.message}`
        );
    } finally {
        if (placeOrderButton) {
            placeOrderButton.disabled = false;
        }
    }
}

// ==================================================
// GROUNDED AI SHOPPING ASSISTANT
// ==================================================

function addAssistantMessage(
    text,
    className = "assistant-message"
) {
    if (!assistantMessages) {
        return null;
    }

    const message = createElement("div", className);

    message.textContent = text;

    assistantMessages.appendChild(message);

    assistantMessages.scrollTop =
        assistantMessages.scrollHeight;

    return message;
}

function renderAssistantCitations(citations) {
    if (
        !assistantMessages ||
        !Array.isArray(citations) ||
        citations.length === 0
    ) {
        return;
    }

    const list = createElement(
        "ul",
        "assistant-citations"
    );

    citations.forEach((citation, index) => {
        let label = "";

        if (typeof citation === "string") {
            label = citation;
        } else if (citation && typeof citation === "object") {
            label =
                citation.title ||
                citation.source ||
                citation.name ||
                citation.document_name ||
                citation.document_id ||
                `Source ${index + 1}`;
        }

        if (label) {
            list.appendChild(
                createElement("li", "", String(label))
            );
        }
    });

    if (list.children.length) {
        assistantMessages.appendChild(
            createElement(
                "p",
                "assistant-citations-title",
                "Sources:"
            )
        );

        assistantMessages.appendChild(list);
    }
}

async function askShoppingAssistant(event) {
    event.preventDefault();

    if (!assistantQuestion || !assistantMessages) {
        return;
    }

    const question = assistantQuestion.value.trim();

    if (!question) {
        setMessage(
            assistantStatus,
            "Please enter your question."
        );

        assistantQuestion.focus();
        return;
    }

    addAssistantMessage(
        `You: ${question}`,
        "assistant-user-message"
    );

    assistantQuestion.value = "";

    if (assistantSendButton) {
        assistantSendButton.disabled = true;
    }

    setMessage(
        assistantStatus,
        "ShopSense AI is searching the available information..."
    );

    const pending = addAssistantMessage(
        "Thinking...",
        "assistant-message assistant-pending"
    );

    try {
        const data = await fetchJSON("/assistant/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                question,
                session_id: sessionId
            })
        });

        pending?.remove();

        const answer =
            data.answer ||
            data.response ||
            data.message ||
            "I could not find a supported answer in the available shop information.";

        addAssistantMessage(
            `ShopSense AI: ${answer}`,
            "assistant-message"
        );

        renderAssistantCitations(
            data.citations || data.sources || []
        );

        setMessage(assistantStatus, "");
    } catch (error) {
        pending?.remove();

        console.error("Assistant error:", error);

        addAssistantMessage(
            `ShopSense AI: Sorry, I could not process your question. ${error.message}`,
            "assistant-message assistant-error"
        );

        setMessage(
            assistantStatus,
            "The assistant request failed. Please try again."
        );
    } finally {
        if (assistantSendButton) {
            assistantSendButton.disabled = false;
        }

        assistantQuestion?.focus();

        assistantMessages.scrollTop =
            assistantMessages.scrollHeight;
    }
}

// ==================================================
// EVENT LISTENERS
// ==================================================

searchButton?.addEventListener("click", loadProducts);

searchInput?.addEventListener("keydown", event => {
    if (event.key === "Enter") {
        event.preventDefault();
        loadProducts();
    }
});

categoryFilter?.addEventListener("change", loadProducts);

sortFilter?.addEventListener("change", loadProducts);

maxPriceInput?.addEventListener("change", loadProducts);

maxPriceInput?.addEventListener("keydown", event => {
    if (event.key === "Enter") {
        event.preventDefault();
        loadProducts();
    }
});

resetButton?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    if (categoryFilter) categoryFilter.value = "";
    if (maxPriceInput) maxPriceInput.value = "";
    if (sortFilter) sortFilter.value = "price_asc";

    loadProducts();
});

recommendButton?.addEventListener(
    "click",
    getRecommendations
);

recommendInput?.addEventListener("keydown", event => {
    if (event.key === "Enter") {
        event.preventDefault();
        getRecommendations();
    }
});

compareButton?.addEventListener(
    "click",
    compareSelectedProducts
);

clearCompareButton?.addEventListener(
    "click",
    clearComparison
);

placeOrderButton?.addEventListener(
    "click",
    placeDemoOrder
);

assistantForm?.addEventListener(
    "submit",
    askShoppingAssistant
);

// ==================================================
// LANGUAGE CHANGE
// ==================================================

document
    .getElementById("languageSelect")
    ?.addEventListener("change", () => {
        displayProducts(currentProducts);
        renderCart();

        if (recommendationList) {
            recommendationList.replaceChildren();
        }

        setMessage(
            recommendMessage,
            translate(
                "noRecommendations",
                "No recommendations yet."
            )
        );
    });

// ==================================================
// START APPLICATION
// ==================================================

document.addEventListener("DOMContentLoaded", () => {
    loadProducts();
    renderCart();
});
