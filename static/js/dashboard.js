/* =========================================================
   RS AI - Full Platform Interactive Logic (JavaScript)
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    loadOverview();
    loadOrders();
    loadProducts();
    loadFaqs();
    loadCommentLogs();
    loadSettings();
    loadOmnichatConversations();
    initSmartphoneSimulator();
    initModals();
});

// ==========================================
// 1. NAVIGATION & TAB SWITCHING
// ==========================================
function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const tabPanes = document.querySelectorAll(".tab-pane");
    const pageTitle = document.getElementById("page-title");
    const pageSubtitle = document.getElementById("page-subtitle");

    const titles = {
        "test-arena": { title: "⚡ AI Setup & Live Simulator", sub: "Configure your sales assistant and test customer conversations live" },
        "dashboard": { title: "📊 Dashboard Overview", sub: "Monitor total conversations, orders, conversion rate and sales" },
        "orders": { title: "📦 Orders Management", sub: "Track, manage and update customer orders across channels" },
        "products": { title: "🏷️ Products & Inventory", sub: "Manage product catalog, prices, stocks and variations" },
        "content": { title: "📚 Train Content & FAQs", sub: "Train your AI with custom Q&A pairs, knowledge base and auto-replies" },
        "omnichat": { title: "💬 Omnichat Inbox", sub: "Multi-channel unified customer conversation inbox" },
        "analytics": { title: "📈 Analytics & Performance", sub: "Key performance metrics, response times and sales trends" },
        "adsflow": { title: "📢 AdsFlow Campaigns", sub: "Automatic lead qualification from Facebook click-to-Messenger ads" },
        "integrations": { title: "🔗 Channels & Integrations", sub: "Connect Facebook Page Messenger, Comments, and WhatsApp Cloud API" },
        "settings": { title: "⚙️ Store & AI Settings", sub: "Configure business details, delivery fees, and AI engine" },
        "support": { title: "📞 Help & Support", sub: "Platform documentation, contact info and FAQs" }
    };

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const target = item.getAttribute("data-tab");
            
            navItems.forEach(n => n.classList.remove("active"));
            tabPanes.forEach(p => p.classList.remove("active"));

            item.classList.add("active");
            const activePane = document.getElementById(`tab-${target}`);
            if (activePane) activePane.classList.add("active");

            if (titles[target]) {
                pageTitle.innerText = titles[target].title;
                pageSubtitle.innerText = titles[target].sub;
            }

            refreshCurrentTab(target);
        });
    });
}

function refreshCurrentTab(target) {
    if (!target) {
        const activeNav = document.querySelector(".nav-item.active");
        target = activeNav ? activeNav.getAttribute("data-tab") : "dashboard";
    }

    if (target === "dashboard") loadOverview();
    if (target === "orders") loadOrders();
    if (target === "products") loadProducts();
    if (target === "content") { loadFaqs(); loadCommentLogs(); }
    if (target === "omnichat") loadOmnichatConversations();
    if (target === "settings" || target === "test-arena") loadSettings();
}

// ==========================================
// 2. OVERVIEW & DASHBOARD METRICS
// ==========================================
async function loadOverview() {
    try {
        const res = await fetch("/api/overview");
        const data = await res.json();

        // Dashboard Stats
        const salesEl = document.getElementById("dash-stat-sales");
        const ordersEl = document.getElementById("dash-stat-orders");
        const convsEl = document.getElementById("dash-stat-convs");
        const rateEl = document.getElementById("dash-stat-conv-rate");

        if (salesEl) salesEl.innerText = `৳${data.total_revenue.toLocaleString()}`;
        if (ordersEl) ordersEl.innerText = data.total_orders;
        if (convsEl) convsEl.innerText = Math.max(1, data.total_orders + 1);
        if (rateEl) {
            const rate = data.total_orders > 0 ? "100%" : "0%";
            rateEl.innerText = rate;
        }

        // Recent Orders
        const tbody = document.getElementById("dash-recent-orders-tbody");
        if (tbody) {
            tbody.innerHTML = "";
            if (!data.recent_orders || data.recent_orders.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 25px;">No orders recorded yet. Orders placed via AI will appear here automatically.</td></tr>`;
                return;
            }

            data.recent_orders.forEach(o => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td><strong>${o.order_code}</strong></td>
                    <td>${o.customer_name}</td>
                    <td>${o.customer_phone}</td>
                    <td><strong>৳${o.total_amount}</strong></td>
                    <td><span class="badge badge-${o.status.toLowerCase()}">${o.status}</span></td>
                    <td>${o.created_at ? o.created_at.split(" ")[0] : ""}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        console.error("Overview error:", e);
    }
}

// ==========================================
// 3. ORDER MANAGEMENT
// ==========================================
let currentOrderStatusFilter = "All";

async function loadOrders(searchQuery = "") {
    const tbody = document.getElementById("orders-tbody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 20px;">Loading orders...</td></tr>`;

    try {
        let url = `/api/orders?status=${currentOrderStatusFilter}`;
        if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;

        const res = await fetch(url);
        const data = await res.json();

        tbody.innerHTML = "";
        if (!data.orders || data.orders.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-dim); padding: 35px;">No orders found.</td></tr>`;
            return;
        }

        data.orders.forEach(o => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${o.order_code}</strong><br><small style="color:var(--text-dim); text-transform: capitalize;">${o.channel}</small></td>
                <td><strong>${o.customer_name}</strong><br><small style="color:var(--text-muted);">${o.customer_phone}</small></td>
                <td style="max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${o.customer_address}">
                    ${o.customer_address}
                </td>
                <td style="max-width: 220px;">${o.items_summary}</td>
                <td><strong>৳${o.total_amount}</strong><br><small style="color:var(--text-dim);">(Del: ৳${o.delivery_charge})</small></td>
                <td>
                    <select class="form-select form-select-sm" style="padding: 4px 8px; font-size: 12px; width: 110px;" onchange="changeOrderStatus(${o.id}, this.value)">
                        <option value="Pending" ${o.status === 'Pending' ? 'selected' : ''}>Pending</option>
                        <option value="Confirmed" ${o.status === 'Confirmed' ? 'selected' : ''}>Confirmed</option>
                        <option value="Processing" ${o.status === 'Processing' ? 'selected' : ''}>Processing</option>
                        <option value="Shipped" ${o.status === 'Shipped' ? 'selected' : ''}>Shipped</option>
                        <option value="Delivered" ${o.status === 'Delivered' ? 'selected' : ''}>Delivered</option>
                        <option value="Cancelled" ${o.status === 'Cancelled' ? 'selected' : ''}>Cancelled</option>
                    </select>
                </td>
                <td>${o.created_at ? o.created_at.split(" ")[0] : ""}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn btn-secondary" style="padding: 4px 8px;" onclick='viewOrderDetails(${JSON.stringify(o)})' title="View Invoice">
                            <i class="fas fa-eye"></i>
                        </button>
                        <button class="btn btn-danger" style="padding: 4px 8px;" onclick="deleteOrder(${o.id})" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Load orders error:", e);
    }
}

function filterOrdersByStatus(status, btnElement) {
    currentOrderStatusFilter = status;
    document.querySelectorAll(".order-filter-btn").forEach(b => b.classList.remove("active", "btn-primary"));
    document.querySelectorAll(".order-filter-btn").forEach(b => b.classList.add("btn-secondary"));
    
    if (btnElement) {
        btnElement.classList.remove("btn-secondary");
        btnElement.classList.add("active", "btn-primary");
    }
    loadOrders();
}

async function changeOrderStatus(orderId, newStatus) {
    try {
        const res = await fetch(`/api/orders/${orderId}/status`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: newStatus })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Order status updated to: ${newStatus}`, "success");
            loadOverview();
        }
    } catch (e) {
        showToast("Failed to update status", "danger");
    }
}

async function deleteOrder(orderId) {
    if (!confirm("Are you sure you want to delete this order?")) return;
    try {
        const res = await fetch(`/api/orders/${orderId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("Order deleted successfully", "success");
            loadOrders();
            loadOverview();
        }
    } catch (e) {
        showToast("Could not delete order", "danger");
    }
}

function viewOrderDetails(o) {
    const modal = document.getElementById("modal-order-details");
    const content = document.getElementById("order-details-content");
    if (!modal || !content) return;

    content.innerHTML = `
        <div style="background: rgba(255,255,255,0.03); padding: 16px; border-radius: 8px; margin-bottom: 16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom: 10px;">
                <h4>Order: <span style="color:var(--primary-light);">${o.order_code}</span></h4>
                <span class="badge badge-${o.status.toLowerCase()}">${o.status}</span>
            </div>
            <p><strong>Customer:</strong> ${o.customer_name}</p>
            <p><strong>Phone:</strong> <a href="tel:${o.customer_phone}" style="color:var(--primary-light); text-decoration:none;">${o.customer_phone}</a></p>
            <p><strong>Delivery Address:</strong> ${o.customer_address}</p>
            <p><strong>Channel:</strong> ${o.channel}</p>
            <p><strong>Date & Time:</strong> ${o.created_at}</p>
        </div>

        <h5 style="margin-bottom: 8px;">Line Items Summary:</h5>
        <div style="background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; margin-bottom: 16px;">
            ${o.items_summary}
        </div>

        <div style="background: var(--primary-soft); border: 1px solid var(--border-glow); padding: 14px; border-radius: 8px;">
            <div style="display:flex; justify-content:space-between; margin-bottom: 4px;">
                <span>Subtotal:</span> <strong>৳${o.subtotal}</strong>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom: 4px;">
                <span>Delivery Fee:</span> <strong>৳${o.delivery_charge}</strong>
            </div>
            <hr style="border-color: rgba(255,255,255,0.1); margin: 8px 0;">
            <div style="display:flex; justify-content:space-between; font-size: 16px;">
                <span>Total Bill:</span> <strong style="color:#34d399;">৳${o.total_amount}</strong>
            </div>
        </div>

        <div style="margin-top: 20px; display:flex; justify-content: flex-end; gap: 10px;">
            <button class="btn btn-secondary" onclick="window.print()"><i class="fas fa-print"></i> Print Invoice</button>
            <button class="btn btn-primary" onclick="closeModal('modal-order-details')">Done</button>
        </div>
    `;
    openModal("modal-order-details");
}

async function handleManualOrder(e) {
    e.preventDefault();
    const form = document.getElementById("form-manual-order");
    const formData = new FormData(form);

    try {
        const res = await fetch("/api/orders", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("Order created successfully!", "success");
            form.reset();
            closeModal("modal-add-order");
            loadOrders();
            loadOverview();
        }
    } catch (e) {
        showToast("Failed to create order", "danger");
    }
}

// ==========================================
// 4. PRODUCT CATALOG
// ==========================================
async function loadProducts() {
    const grid = document.getElementById("products-grid");
    if (!grid) return;

    try {
        const res = await fetch("/api/products");
        const data = await res.json();

        grid.innerHTML = "";
        if (!data.products || data.products.length === 0) {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-dim); padding: 40px;">No products added yet. Click '+ Add New Product' above.</div>`;
            return;
        }

        data.products.forEach(p => {
            const card = document.createElement("div");
            card.className = "product-card";
            const imgUrl = p.image_url || "/static/uploads/sample_panjabi.jpg";
            const priceHtml = p.discount_price 
                ? `<span>৳${p.discount_price}</span> <span class="product-old-price">৳${p.price}</span>` 
                : `<span>৳${p.price}</span>`;

            card.innerHTML = `
                <img src="${imgUrl}" alt="${p.name}" class="product-thumb" onerror="this.src='/static/uploads/sample_panjabi.jpg'">
                <div class="product-body">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="product-code">${p.code}</span>
                        <span class="badge ${p.stock > 0 ? 'badge-delivered' : 'badge-cancelled'}">${p.stock > 0 ? `Stock: ${p.stock}` : 'Out of stock'}</span>
                    </div>
                    <h4 class="product-name">${p.name}</h4>
                    <div class="product-price">${priceHtml}</div>
                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 6px; flex: 1;">${p.description || ''}</p>
                    <div class="product-footer">
                        <span style="font-size: 11px; color: var(--text-dim);">${p.category}</span>
                        <button class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="deleteProduct(${p.id})">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        });
    } catch (e) {
        console.error("Load products error:", e);
    }
}

async function handleAddProduct(e) {
    e.preventDefault();
    const form = document.getElementById("form-add-product");
    const formData = new FormData(form);

    try {
        const res = await fetch("/api/products", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("Product added successfully!", "success");
            form.reset();
            closeModal("modal-add-product");
            loadProducts();
            loadOverview();
        }
    } catch (e) {
        showToast("Could not add product", "danger");
    }
}

async function deleteProduct(productId) {
    if (!confirm("Are you sure you want to delete this product?")) return;
    try {
        const res = await fetch(`/api/products/${productId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("Product deleted", "success");
            loadProducts();
            loadOverview();
        }
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ==========================================
// 5. TRAIN CONTENT & FAQS
// ==========================================
function switchContentSubtab(tab, btn) {
    document.querySelectorAll(".content-subtab-btn").forEach(b => {
        b.classList.remove("btn-primary");
        b.classList.add("btn-secondary");
    });
    if (btn) {
        btn.classList.remove("btn-secondary");
        btn.classList.add("btn-primary");
    }

    document.getElementById("content-subtab-faqs").style.display = tab === "faqs" ? "block" : "none";
    document.getElementById("content-subtab-comments").style.display = tab === "comments" ? "block" : "none";
}

async function loadFaqs() {
    const container = document.getElementById("faqs-list-container");
    if (!container) return;

    try {
        const res = await fetch("/api/faqs");
        const data = await res.json();

        container.innerHTML = "";
        if (!data.faqs || data.faqs.length === 0) {
            container.innerHTML = `<div style="text-align: center; color: var(--text-dim); padding: 25px;">No custom Q&A pairs added yet.</div>`;
            return;
        }

        data.faqs.forEach(f => {
            const div = document.createElement("div");
            div.style.cssText = "background: rgba(255,255,255,0.025); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: flex-start;";
            div.innerHTML = `
                <div>
                    <strong style="color:#fff; font-size: 13.5px;"><i class="fas fa-question-circle" style="color:var(--primary-light);"></i> Q: ${f.question}</strong>
                    <p style="font-size: 13px; color: var(--text-muted); margin-top: 6px; line-height: 1.5;"><strong>A:</strong> ${f.answer}</p>
                </div>
                <button class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="deleteFaq(${f.id})">
                    <i class="fas fa-trash"></i>
                </button>
            `;
            container.appendChild(div);
        });
    } catch (e) {
        console.error("Load FAQs error:", e);
    }
}

async function handleAddFaq(e) {
    e.preventDefault();
    const q = document.getElementById("faq-question").value.trim();
    const a = document.getElementById("faq-answer").value.trim();

    if (!q || !a) return;

    try {
        const res = await fetch("/api/faqs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: q, answer: a })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Q&A Pair added to AI training!", "success");
            document.getElementById("faq-question").value = "";
            document.getElementById("faq-answer").value = "";
            loadFaqs();
        }
    } catch (e) {
        showToast("Could not add FAQ", "danger");
    }
}

async function deleteFaq(faqId) {
    try {
        const res = await fetch(`/api/faqs/${faqId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("FAQ removed", "success");
            loadFaqs();
        }
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ==========================================
// 6. COMMENT AUTOMATION LOGS
// ==========================================
async function loadCommentLogs() {
    const tbody = document.getElementById("comments-tbody");
    if (!tbody) return;

    try {
        const res = await fetch("/api/comments/logs");
        const data = await res.json();

        tbody.innerHTML = "";
        if (!data.logs || data.logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-dim); padding: 25px;">No comments received yet. Incoming post comments will be logged here.</td></tr>`;
            return;
        }

        data.logs.forEach(l => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${l.user_name || 'Customer'}</strong></td>
                <td>"${l.comment_text}"</td>
                <td><small style="color: #34d399;">${l.public_reply || '—'}</small></td>
                <td><small style="color: #60a5fa;">${l.private_reply ? l.private_reply.substring(0, 50) + '...' : '—'}</small></td>
                <td>${l.replied_at || ''}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Load comment logs error:", e);
    }
}

// ==========================================
// 7. OMNICHAT (INBOX)
// ==========================================
let activeConversationId = null;

async function loadOmnichatConversations() {
    const container = document.getElementById("omnichat-threads-list");
    if (!container) return;

    try {
        const res = await fetch("/api/omnichat/conversations");
        const data = await res.json();

        container.innerHTML = "";
        if (!data.conversations || data.conversations.length === 0) {
            container.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--text-dim);">No active conversations.</div>`;
            return;
        }

        data.conversations.forEach((c, idx) => {
            const item = document.createElement("div");
            item.style.cssText = "padding: 12px 16px; border-bottom: 1px solid var(--border-color); cursor: pointer; transition: var(--transition);";
            if (idx === 0 && !activeConversationId) {
                activeConversationId = c.id;
                item.style.background = "var(--primary-soft)";
            }
            item.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <strong style="color: #fff; font-size: 13.5px;">${c.customer_name || 'Customer'}</strong>
                    <span class="badge badge-confirmed" style="font-size: 9.5px;">${c.channel}</span>
                </div>
                <div style="font-size: 12px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    ${c.last_message || ''}
                </div>
            `;
            item.addEventListener("click", () => {
                activeConversationId = c.id;
                document.querySelectorAll("#omnichat-threads-list > div").forEach(d => d.style.background = "transparent");
                item.style.background = "var(--primary-soft)";
                document.getElementById("omnichat-active-customer-name").innerText = c.customer_name || 'Customer';
                loadOmnichatMessages(c.id);
            });
            container.appendChild(item);
        });

        if (activeConversationId) loadOmnichatMessages(activeConversationId);
    } catch (e) {
        console.error("Load Omnichat conversations error:", e);
    }
}

async function loadOmnichatMessages(cid) {
    const container = document.getElementById("omnichat-messages-container");
    if (!container) return;

    try {
        const res = await fetch(`/api/omnichat/messages/${cid}`);
        const data = await res.json();

        container.innerHTML = "";
        data.messages.forEach(m => {
            const div = document.createElement("div");
            div.className = `message-bubble ${m.sender_type === 'user' ? 'message-user' : 'message-bot'}`;
            div.innerHTML = `<div>${m.content.replace(/\n/g, "<br>")}</div>`;
            container.appendChild(div);
        });
        container.scrollTop = container.scrollHeight;
    } catch (e) {
        console.error("Load Omnichat messages error:", e);
    }
}

async function handleOmnichatSend(e) {
    e.preventDefault();
    const input = document.getElementById("omnichat-reply-input");
    const text = input.value.trim();
    if (!text || !activeConversationId) return;

    try {
        const res = await fetch("/api/omnichat/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ conversation_id: activeConversationId, content: text })
        });
        const data = await res.json();
        if (data.success) {
            input.value = "";
            loadOmnichatMessages(activeConversationId);
            loadOmnichatConversations();
        }
    } catch (e) {
        showToast("Send failed", "danger");
    }
}

// ==========================================
// 8. SETTINGS & AI CONFIGURATION
// ==========================================
let isAIMasterActive = true;

async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        const s = data.settings || {};

        // Master Switch state
        isAIMasterActive = (s.ai_enabled !== "false");
        updateAIMasterButtonUI(isAIMasterActive);

        // Settings tab inputs
        if (document.getElementById("setting-shop-name")) document.getElementById("setting-shop-name").value = s.shop_name || "";
        if (document.getElementById("setting-shop-phone")) document.getElementById("setting-shop-phone").value = s.shop_phone || "";
        if (document.getElementById("setting-delivery-inside")) document.getElementById("setting-delivery-inside").value = s.delivery_inside_dhaka || "70";
        if (document.getElementById("setting-delivery-outside")) document.getElementById("setting-delivery-outside").value = s.delivery_outside_dhaka || "130";
        if (document.getElementById("setting-fb-token")) document.getElementById("setting-fb-token").value = s.fb_page_access_token || "";
        if (document.getElementById("setting-wa-token")) document.getElementById("setting-wa-token").value = s.whatsapp_access_token || "";
        if (document.getElementById("setting-wa-phone-id")) document.getElementById("setting-wa-phone-id").value = s.whatsapp_phone_number_id || "";
        if (document.getElementById("setting-comment-reply-template")) document.getElementById("setting-comment-reply-template").value = s.comment_reply_template || "";

        // Dynamic Webhook URLs based on current origin
        const currentOrigin = window.location.origin;
        if (document.getElementById("setting-fb-webhook-display")) {
            document.getElementById("setting-fb-webhook-display").value = `${currentOrigin}/webhook/facebook`;
        }
        if (document.getElementById("setting-wa-webhook-display")) {
            document.getElementById("setting-wa-webhook-display").value = `${currentOrigin}/webhook/whatsapp`;
        }

        // AI Arena Setup tab inputs
        if (document.getElementById("arena-shop-name")) document.getElementById("arena-shop-name").value = s.shop_name || "";
        if (document.getElementById("arena-gemini-key")) document.getElementById("arena-gemini-key").value = s.gemini_api_key || "";
        if (document.getElementById("arena-system-prompt")) document.getElementById("arena-system-prompt").value = s.ai_system_prompt || "";
        if (document.getElementById("phone-header-shop-name")) document.getElementById("phone-header-shop-name").innerText = s.shop_name || "My Shop Admin";

    } catch (e) {
        console.error("Load settings error:", e);
    }
}

function updateAIMasterButtonUI(active) {
    const btn = document.getElementById("ai-master-toggle-btn");
    const text = document.getElementById("ai-master-status-text");
    if (!btn || !text) return;

    if (active) {
        btn.style.background = "rgba(16, 185, 129, 0.15)";
        btn.style.borderColor = "#10b981";
        btn.style.color = "#34d399";
        btn.innerHTML = `<i class="fas fa-circle" style="font-size: 9px; color: #34d399;"></i> <span id="ai-master-status-text">AI Agent: Active (Auto-Reply)</span>`;
    } else {
        btn.style.background = "rgba(239, 68, 68, 0.15)";
        btn.style.borderColor = "#ef4444";
        btn.style.color = "#f87171";
        btn.innerHTML = `<i class="fas fa-pause-circle" style="font-size: 11px; color: #f87171;"></i> <span id="ai-master-status-text">AI Agent: Paused (Manual Mode)</span>`;
    }
}

async function toggleAIMasterSwitch() {
    isAIMasterActive = !isAIMasterActive;
    updateAIMasterButtonUI(isAIMasterActive);

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ai_enabled: isAIMasterActive ? "true" : "false" })
        });
        const data = await res.json();
        if (data.success) {
            if (isAIMasterActive) {
                showToast("🟢 এআই এজেন্ট চালু করা হয়েছে (২৪ ঘণ্টা অটো-রিপ্লাই মোড)", "success");
            } else {
                showToast("⏸️ এআই এজেন্ট বন্ধ করা হয়েছে (ম্যানুয়াল মোড)", "danger");
            }
        }
    } catch (e) {
        showToast("Switch update failed", "danger");
    }
}

async function saveAllSettings(e) {
    if (e) e.preventDefault();
    const payload = {
        shop_name: document.getElementById("setting-shop-name") ? document.getElementById("setting-shop-name").value : "আমার ই-কমার্স শপ",
        shop_phone: document.getElementById("setting-shop-phone") ? document.getElementById("setting-shop-phone").value : "01700000000",
        delivery_inside_dhaka: document.getElementById("setting-delivery-inside") ? document.getElementById("setting-delivery-inside").value : "70",
        delivery_outside_dhaka: document.getElementById("setting-delivery-outside") ? document.getElementById("setting-delivery-outside").value : "130",
        comment_reply_template: document.getElementById("setting-comment-reply-template") ? document.getElementById("setting-comment-reply-template").value : "",
        comment_auto_reply: document.getElementById("setting-auto-comment") ? (document.getElementById("setting-auto-comment").checked ? "true" : "false") : "true",
        private_message_on_comment: document.getElementById("setting-private-inbox") ? (document.getElementById("setting-private-inbox").checked ? "true" : "false") : "true",
        fb_page_access_token: document.getElementById("setting-fb-token") ? document.getElementById("setting-fb-token").value : "",
        whatsapp_access_token: document.getElementById("setting-wa-token") ? document.getElementById("setting-wa-token").value : "",
        whatsapp_phone_number_id: document.getElementById("setting-wa-phone-id") ? document.getElementById("setting-wa-phone-id").value : ""
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("Settings saved successfully!", "success");
        }
    } catch (e) {
        showToast("Failed to save settings", "danger");
    }
}

async function saveArenaSettings() {
    const payload = {
        shop_name: document.getElementById("arena-shop-name").value,
        gemini_api_key: document.getElementById("arena-gemini-key").value,
        ai_system_prompt: document.getElementById("arena-system-prompt").value
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("AI Brain synchronized & updated!", "success");
            if (document.getElementById("phone-header-shop-name")) {
                document.getElementById("phone-header-shop-name").innerText = payload.shop_name;
            }
        }
    } catch (e) {
        showToast("Sync failed", "danger");
    }
}

function setTrainerPrompt(snippet) {
    const ta = document.getElementById("arena-system-prompt");
    if (ta) {
        ta.value += (ta.value ? "\n" : "") + snippet;
        showToast("Shortcut added to AI knowledge prompt", "info");
    }
}

// ==========================================
// 9. SMARTPHONE CUSTOMER SIMULATOR (Presswayy Style)
// ==========================================
let currentSelectedPhoneImage = null;

function initSmartphoneSimulator() {
    const form = document.getElementById("phone-input-form");
    const input = document.getElementById("phone-text-input");
    const imageInput = document.getElementById("phone-image-upload");
    const previewBar = document.getElementById("phone-image-preview-bar");
    const previewThumb = document.getElementById("phone-image-preview-thumb");
    const previewName = document.getElementById("phone-image-preview-name");

    if (!form || !input) return;

    // Handle Image Selection from File Dialog
    if (imageInput) {
        imageInput.addEventListener("change", () => {
            if (imageInput.files && imageInput.files[0]) {
                const file = imageInput.files[0];
                currentSelectedPhoneImage = file;
                if (previewThumb) previewThumb.src = URL.createObjectURL(file);
                if (previewName) previewName.innerText = file.name;
                if (previewBar) previewBar.style.display = "flex";
                input.focus();
                showToast("📷 ছবি সিলেক্ট করা হয়েছে। মেসেজ লিখে বা সরাসরি 'Send' চাপুন।", "info");
            }
        });
    }

    // Support Pasting Images directly from Clipboard (Ctrl+V)
    input.addEventListener("paste", (e) => {
        const items = (e.clipboardData || e.originalEvent.clipboardData).items;
        for (let item of items) {
            if (item.type.indexOf("image") !== -1) {
                const blob = item.getAsFile();
                currentSelectedPhoneImage = blob;
                if (previewThumb) previewThumb.src = URL.createObjectURL(blob);
                if (previewName) previewName.innerText = "Pasted Screenshot.png";
                if (previewBar) previewBar.style.display = "flex";
                showToast("📷 স্ক্রিনশট পেস্ট হয়েছে!", "info");
                break;
            }
        }
    });

    // Form Submission (Text and/or Image)
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = input.value.trim();
        const imgFile = currentSelectedPhoneImage || (imageInput && imageInput.files ? imageInput.files[0] : null);

        if (!text && !imgFile) return;

        // Render User Message in Chat
        appendPhoneMessage("user", text, imgFile ? URL.createObjectURL(imgFile) : null);
        input.value = "";
        cancelPhoneImage();

        const formData = new FormData();
        if (text) formData.append("message", text);
        if (imgFile) formData.append("image", imgFile);
        formData.append("generate_voice", "false");

        const typingEl = appendPhoneTyping();

        try {
            const res = await fetch("/api/test/chat", {
                method: "POST",
                body: formData
            });
            const data = await res.json();
            if (typingEl) typingEl.remove();

            appendPhoneMessage("bot", data.reply_text, null, data.matched_images);

            if (data.order_created) {
                renderPhoneDetectedOrder(data.order_created);
                showToast(`🎉 Order successfully placed: #${data.order_created.order_code}`, "success");
                loadOverview();
                loadOrders();
            }
        } catch (err) {
            if (typingEl) typingEl.remove();
            appendPhoneMessage("bot", "Could not connect to AI. Please verify your Gemini API key.");
        }
    });
}

function cancelPhoneImage() {
    currentSelectedPhoneImage = null;
    const imageInput = document.getElementById("phone-image-upload");
    if (imageInput) imageInput.value = "";
    const previewBar = document.getElementById("phone-image-preview-bar");
    if (previewBar) previewBar.style.display = "none";
}

function sendPhoneQuickQuery(text) {
    const input = document.getElementById("phone-text-input");
    const form = document.getElementById("phone-input-form");
    if (input && form) {
        input.value = text;
        form.dispatchEvent(new Event("submit"));
    }
}

function appendPhoneMessage(sender, text, imgUrl = null, matchedImages = []) {
    const container = document.getElementById("phone-messages");
    if (!container) return;

    const div = document.createElement("div");
    div.className = `message-bubble message-${sender}`;

    let html = "";
    if (imgUrl) {
        html += `<img src="${imgUrl}" style="max-width: 100%; border-radius: 8px; margin-bottom: 6px; display: block;">`;
    }
    if (text) {
        html += `<div>${text.replace(/\n/g, "<br>")}</div>`;
    }
    if (matchedImages && matchedImages.length > 0) {
        html += `<div style="display:flex; gap:6px; margin-top:6px; flex-wrap:wrap;">`;
        matchedImages.forEach(img => {
            html += `<img src="${img}" style="width: 70px; height: 70px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border-color);">`;
        });
        html += `</div>`;
    }

    div.innerHTML = html;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendPhoneTyping() {
    const container = document.getElementById("phone-messages");
    const div = document.createElement("div");
    div.className = "message-bubble message-bot";
    div.innerHTML = `<span style="font-style: italic; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Typing...</span>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function clearPhoneChat() {
    const container = document.getElementById("phone-messages");
    if (container) {
        container.innerHTML = `<div class="message-bubble message-bot">আসসালামু আলাইকুম আপু/ভাইয়া! 😊 আমাদের শপে আপনাকে স্বাগতম। আপনি কোনো প্রডাক্টের তথ্য জানতে চান বা অর্ডার করতে চান?</div>`;
    }
    const orderCard = document.getElementById("phone-detected-order-card");
    if (orderCard) orderCard.style.display = "none";
}

function renderPhoneDetectedOrder(order) {
    const card = document.getElementById("phone-detected-order-card");
    if (!card) return;

    card.style.display = "block";
    card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 4px;">
            <strong style="color:#34d399; font-size: 12px;"><i class="fas fa-check-circle"></i> New Order Captured!</strong>
            <span class="badge badge-pending" style="font-size: 9px;">Pending</span>
        </div>
        <div style="font-size: 11.5px; color: #fff;">
            <strong>#${order.order_code}</strong> | ${order.customer_name} (${order.customer_phone})<br>
            <strong>Total: ৳${order.total_amount}</strong> (Delivery: ৳${order.delivery_charge})
        </div>
    `;
}

// ==========================================
// 10. MODALS & TOASTS
// ==========================================
function initModals() {
    document.querySelectorAll(".modal-overlay").forEach(m => {
        m.addEventListener("click", (e) => {
            if (e.target === m) m.classList.remove("active");
        });
    });
}

function openModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.add("active");
}

function closeModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.remove("active");
}

function showToast(message, type = "info") {
    const container = document.getElementById("toast-container") || createToastContainer();
    const toast = document.createElement("div");
    toast.className = `toast`;
    
    let icon = "fa-info-circle";
    if (type === "success") icon = "fa-check-circle";
    if (type === "danger") icon = "fa-exclamation-circle";

    toast.innerHTML = `<i class="fas ${icon}" style="color: var(--${type});"></i> <span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function createToastContainer() {
    const div = document.createElement("div");
    div.id = "toast-container";
    div.className = "toast-container";
    document.body.appendChild(div);
    return div;
}
