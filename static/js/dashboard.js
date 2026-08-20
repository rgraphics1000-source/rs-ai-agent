/* =========================================================
   RS AI - Full Platform Interactive Logic (JavaScript)
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    loadOverview();
    loadOrders();
    loadProducts();
    loadTrainingRules();
    loadSavedMediaList();
    loadFaqs();
    loadCommentLogs();
    loadSettings();
    loadOmnichatConversations();
    initSmartphoneSimulator();
    initModals();
    initPWA();
});

function initPWA() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js')
            .then(() => console.log("[PWA] Service worker registered"))
            .catch(err => console.log("[PWA] SW register error:", err));
    }
}

// ==========================================
// 1. NAVIGATION & TAB SWITCHING (DESKTOP & MOBILE)
// ==========================================
function toggleMobileSidebar() {
    const sidebar = document.getElementById("app-sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (!sidebar) return;

    sidebar.classList.toggle("mobile-open");
    if (backdrop) backdrop.classList.toggle("active");
}

function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const mobileNavLinks = document.querySelectorAll(".mobile-nav-link[data-tab]");
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

    function switchTab(target) {
        if (!target) return;

        navItems.forEach(n => {
            if (n.getAttribute("data-tab") === target) n.classList.add("active");
            else n.classList.remove("active");
        });

        mobileNavLinks.forEach(m => {
            if (m.getAttribute("data-tab") === target) m.classList.add("active");
            else m.classList.remove("active");
        });

        tabPanes.forEach(p => p.classList.remove("active"));
        const activePane = document.getElementById(`tab-${target}`);
        if (activePane) activePane.classList.add("active");

        if (titles[target] && pageTitle && pageSubtitle) {
            pageTitle.innerText = titles[target].title;
            pageSubtitle.innerText = titles[target].sub;
        }

        // Close mobile drawer if open
        const sidebar = document.getElementById("app-sidebar");
        const backdrop = document.getElementById("sidebar-backdrop");
        if (sidebar && sidebar.classList.contains("mobile-open")) {
            sidebar.classList.remove("mobile-open");
            if (backdrop) backdrop.classList.remove("active");
        }

        refreshCurrentTab(target);
    }

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const target = item.getAttribute("data-tab");
            switchTab(target);
        });
    });

    mobileNavLinks.forEach(item => {
        item.addEventListener("click", () => {
            const target = item.getAttribute("data-tab");
            switchTab(target);
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
// 4. PRODUCT CATALOG (MULTI-IMAGE SUPPORT)
// ==========================================
let addProductSelectedFiles = [];
let editProductExistingImages = [];
let editProductNewFiles = [];

function previewAddProductImages(e) {
    const files = Array.from(e.target.files);
    addProductSelectedFiles = addProductSelectedFiles.concat(files);
    renderAddProductPreviews();
}

function renderAddProductPreviews() {
    const wrapper = document.getElementById("add-prod-preview-wrapper");
    const container = document.getElementById("add-prod-images-preview");
    if (!container || !wrapper) return;

    if (addProductSelectedFiles.length === 0) {
        wrapper.style.display = "none";
        container.innerHTML = "";
        return;
    }

    wrapper.style.display = "block";
    container.innerHTML = "";

    addProductSelectedFiles.forEach((file, idx) => {
        const item = document.createElement("div");
        item.style.position = "relative";
        item.style.width = "70px";
        item.style.height = "70px";
        item.style.borderRadius = "6px";
        item.style.overflow = "hidden";
        item.style.border = idx === 0 ? "2px solid #ea580c" : "1px solid var(--border-glass)";

        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "cover";

        const badge = document.createElement("span");
        if (idx === 0) {
            badge.innerText = "Cover";
            badge.style.position = "absolute";
            badge.style.bottom = "0";
            badge.style.left = "0";
            badge.style.right = "0";
            badge.style.background = "rgba(234, 88, 12, 0.85)";
            badge.style.fontSize = "9px";
            badge.style.textAlign = "center";
            badge.style.color = "#fff";
            badge.style.fontWeight = "bold";
        }

        const delBtn = document.createElement("button");
        delBtn.innerHTML = "&times;";
        delBtn.type = "button";
        delBtn.style.position = "absolute";
        delBtn.style.top = "2px";
        delBtn.style.right = "2px";
        delBtn.style.background = "rgba(239, 68, 68, 0.9)";
        delBtn.style.color = "#fff";
        delBtn.style.border = "none";
        delBtn.style.borderRadius = "50%";
        delBtn.style.width = "18px";
        delBtn.style.height = "18px";
        delBtn.style.cursor = "pointer";
        delBtn.style.fontSize = "12px";
        delBtn.style.lineHeight = "1";
        delBtn.onclick = () => {
            addProductSelectedFiles.splice(idx, 1);
            renderAddProductPreviews();
        };

        item.appendChild(img);
        if (idx === 0) item.appendChild(badge);
        item.appendChild(delBtn);
        container.appendChild(item);
    });
}

function previewEditProductImages(e) {
    const files = Array.from(e.target.files);
    editProductNewFiles = editProductNewFiles.concat(files);
    renderEditProductPreviews();
}

function renderEditProductPreviews() {
    const container = document.getElementById("edit-prod-images-preview");
    if (!container) return;
    container.innerHTML = "";

    // Render existing images
    editProductExistingImages.forEach((url, idx) => {
        const item = document.createElement("div");
        item.style.position = "relative";
        item.style.width = "70px";
        item.style.height = "70px";
        item.style.borderRadius = "6px";
        item.style.overflow = "hidden";
        item.style.border = idx === 0 ? "2px solid #ea580c" : "1px solid var(--border-glass)";

        const img = document.createElement("img");
        img.src = url;
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "cover";

        const delBtn = document.createElement("button");
        delBtn.innerHTML = "&times;";
        delBtn.type = "button";
        delBtn.style.position = "absolute";
        delBtn.style.top = "2px";
        delBtn.style.right = "2px";
        delBtn.style.background = "rgba(239, 68, 68, 0.9)";
        delBtn.style.color = "#fff";
        delBtn.style.border = "none";
        delBtn.style.borderRadius = "50%";
        delBtn.style.width = "18px";
        delBtn.style.height = "18px";
        delBtn.style.cursor = "pointer";
        delBtn.style.fontSize = "12px";
        delBtn.style.lineHeight = "1";
        delBtn.onclick = () => {
            editProductExistingImages.splice(idx, 1);
            renderEditProductPreviews();
        };

        item.appendChild(img);
        item.appendChild(delBtn);
        container.appendChild(item);
    });

    // Render newly selected files
    editProductNewFiles.forEach((file, idx) => {
        const item = document.createElement("div");
        item.style.position = "relative";
        item.style.width = "70px";
        item.style.height = "70px";
        item.style.borderRadius = "6px";
        item.style.overflow = "hidden";
        item.style.border = "1px dashed #34d399";

        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "cover";

        const delBtn = document.createElement("button");
        delBtn.innerHTML = "&times;";
        delBtn.type = "button";
        delBtn.style.position = "absolute";
        delBtn.style.top = "2px";
        delBtn.style.right = "2px";
        delBtn.style.background = "rgba(239, 68, 68, 0.9)";
        delBtn.style.color = "#fff";
        delBtn.style.border = "none";
        delBtn.style.borderRadius = "50%";
        delBtn.style.width = "18px";
        delBtn.style.height = "18px";
        delBtn.style.cursor = "pointer";
        delBtn.style.fontSize = "12px";
        delBtn.style.lineHeight = "1";
        delBtn.onclick = () => {
            editProductNewFiles.splice(idx, 1);
            renderEditProductPreviews();
        };

        item.appendChild(img);
        item.appendChild(delBtn);
        container.appendChild(item);
    });
}

let cachedProductsList = [];

async function loadProducts() {
    const grid = document.getElementById("products-grid");
    if (!grid) return;

    try {
        const res = await fetch("/api/products");
        const data = await res.json();
        let products = data.products || [];

        if (products.length > 0) {
            localStorage.setItem("rs_cached_products", JSON.stringify(products));
        } else {
            // Check if we have backup in localStorage to auto-restore
            const savedLocal = localStorage.getItem("rs_cached_products");
            if (savedLocal) {
                try {
                    const parsed = JSON.parse(savedLocal);
                    if (Array.isArray(parsed) && parsed.length > 0) {
                        await fetch("/api/products/batch-restore", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ products: parsed })
                        });
                        const refreshRes = await fetch("/api/products");
                        const refreshData = await refreshRes.json();
                        products = refreshData.products || parsed;
                    }
                } catch (e) {
                    console.error("Auto-restore products error:", e);
                }
            }
        }

        cachedProductsList = products;
        grid.innerHTML = "";
        if (products.length === 0) {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-dim); padding: 40px;">No products added yet. Click '+ Add New Product' above.</div>`;
            return;
        }

        data.products.forEach(p => {
            const card = document.createElement("div");
            card.className = "product-card";
            const gallery = (p.gallery_images && p.gallery_images.length > 0) ? p.gallery_images : (p.image_url ? [p.image_url] : ["/static/uploads/sample_panjabi.jpg"]);
            const coverImg = gallery[0];
            const priceHtml = p.discount_price 
                ? `<span>৳${p.discount_price}</span> <span class="product-old-price">৳${p.price}</span>` 
                : `<span>৳${p.price}</span>`;

            const photoBadge = gallery.length > 1 
                ? `<span style="position:absolute; top: 10px; right: 10px; background: rgba(10,13,20,0.85); color: #fff; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; cursor: pointer; border: 1px solid rgba(255,255,255,0.2);" onclick="openProductGallery(${p.id})"><i class="fas fa-images"></i> ${gallery.length} Photos</span>` 
                : '';

            card.innerHTML = `
                <div style="position: relative; cursor: pointer;" onclick="openProductGallery(${p.id})">
                    <img src="${coverImg}" alt="${p.name}" class="product-thumb" onerror="this.src='/static/uploads/sample_panjabi.jpg'">
                    ${photoBadge}
                </div>
                <div class="product-body">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="product-code">${p.code}</span>
                        <span class="badge ${p.stock > 0 ? 'badge-delivered' : 'badge-cancelled'}">${p.stock > 0 ? `Stock: ${p.stock}` : 'Out of stock'}</span>
                    </div>
                    <h4 class="product-name" style="cursor: pointer;" onclick="openProductGallery(${p.id})">${p.name}</h4>
                    <div class="product-price">${priceHtml}</div>
                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 6px; flex: 1;">${p.description || ''}</p>
                    
                    ${gallery.length > 1 ? `
                    <div style="display:flex; gap: 4px; margin: 8px 0; overflow-x: auto;">
                        ${gallery.slice(0, 4).map(u => `<img src="${u}" style="width: 32px; height: 32px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border-glass);" onclick="openProductGallery(${p.id})">`).join('')}
                        ${gallery.length > 4 ? `<span style="font-size: 10px; align-self: center; color: var(--text-muted);">+${gallery.length - 4}</span>` : ''}
                    </div>` : ''}

                    <div class="product-footer">
                        <span style="font-size: 11px; color: var(--text-dim);">${p.category}</span>
                        <div style="display: flex; gap: 6px;">
                            <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px;" onclick="openEditProductModal(${p.id})">
                                <i class="fas fa-edit"></i> Edit
                            </button>
                            <button class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="deleteProduct(${p.id})">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
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

    // Remove single file image if present, and append all addProductSelectedFiles
    formData.delete("image");
    formData.delete("images");
    addProductSelectedFiles.forEach(file => {
        formData.append("images", file);
    });

    try {
        const res = await fetch("/api/products", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("Product added with all photos!", "success");
            form.reset();
            addProductSelectedFiles = [];
            renderAddProductPreviews();
            closeModal("modal-add-product");
            loadProducts();
            loadOverview();
        }
    } catch (e) {
        showToast("Could not add product", "danger");
    }
}

function openEditProductModal(productId) {
    const p = cachedProductsList.find(item => item.id === productId);
    if (!p) return;

    document.getElementById("edit-prod-id").value = p.id;
    document.getElementById("edit-prod-name").value = p.name || "";
    document.getElementById("edit-prod-code").value = p.code || "";
    document.getElementById("edit-prod-category").value = p.category || "General";
    document.getElementById("edit-prod-price").value = p.price || "";
    document.getElementById("edit-prod-discount-price").value = p.discount_price || "";
    document.getElementById("edit-prod-stock").value = p.stock || "10";
    document.getElementById("edit-prod-description").value = p.description || "";

    editProductExistingImages = (p.gallery_images && p.gallery_images.length > 0) ? [...p.gallery_images] : (p.image_url ? [p.image_url] : []);
    editProductNewFiles = [];
    renderEditProductPreviews();

    openModal("modal-edit-product");
}

async function handleEditProduct(e) {
    e.preventDefault();
    const productId = document.getElementById("edit-prod-id").value;
    const formData = new FormData();
    formData.append("name", document.getElementById("edit-prod-name").value);
    formData.append("code", document.getElementById("edit-prod-code").value);
    formData.append("category", document.getElementById("edit-prod-category").value);
    formData.append("price", document.getElementById("edit-prod-price").value);
    formData.append("discount_price", document.getElementById("edit-prod-discount-price").value);
    formData.append("stock", document.getElementById("edit-prod-stock").value);
    formData.append("description", document.getElementById("edit-prod-description").value);
    formData.append("existing_images", JSON.stringify(editProductExistingImages));

    editProductNewFiles.forEach(file => {
        formData.append("images", file);
    });

    try {
        const res = await fetch(`/api/products/${productId}/edit`, {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("Product updated successfully!", "success");
            closeModal("modal-edit-product");
            loadProducts();
        }
    } catch (e) {
        showToast("Update failed", "danger");
    }
}

function openProductGallery(productId) {
    const p = cachedProductsList.find(item => item.id === productId);
    if (!p) return;

    const gallery = (p.gallery_images && p.gallery_images.length > 0) ? p.gallery_images : (p.image_url ? [p.image_url] : ["/static/uploads/sample_panjabi.jpg"]);
    const title = document.getElementById("gallery-modal-title");
    const body = document.getElementById("gallery-modal-body");
    if (!title || !body) return;

    title.innerHTML = `<i class="fas fa-images" style="color:var(--primary-light);"></i> ${p.name} (${gallery.length} Photos)`;

    body.innerHTML = `
        <div style="margin-bottom: 12px;">
            <img id="gallery-main-view" src="${gallery[0]}" style="width: 100%; max-height: 380px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.4);">
        </div>
        <div style="display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; max-height: 100px; overflow-y: auto; padding: 6px;">
            ${gallery.map((url, idx) => `
                <img src="${url}" style="width: 60px; height: 60px; object-fit: cover; border-radius: 6px; cursor: pointer; border: ${idx === 0 ? '2px solid #ea580c' : '1px solid var(--border-glass)'};" onclick="document.getElementById('gallery-main-view').src='${url}'; this.parentElement.querySelectorAll('img').forEach(i => i.style.border='1px solid var(--border-glass)'); this.style.border='2px solid #ea580c';">
            `).join('')}
        </div>
        <div style="margin-top: 14px; text-align: left; background: rgba(255,255,255,0.03); padding: 12px; border-radius: 8px;">
            <div style="display: flex; justify-content: space-between;">
                <span style="font-weight: 600; font-size: 15px;">${p.name}</span>
                <span style="color: #34d399; font-weight: 700;">৳${p.discount_price || p.price}</span>
            </div>
            <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">${p.description || ''}</p>
        </div>
    `;

    openModal("modal-view-gallery");
}

async function deleteProduct(productId) {
    if (!confirm("Are you sure you want to delete this product?")) return;
    try {
        const res = await fetch(`/api/products/${productId}/delete`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Product deleted successfully!", "success");
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
// 6. CONTENT & AI BRAIN TRAINING SUBTABS
// ==========================================
function switchContentSubtab(subtab, btn) {
    document.querySelectorAll(".content-subtab-btn").forEach(b => {
        b.className = "btn btn-secondary content-subtab-btn";
    });
    if (btn) btn.className = "btn btn-primary content-subtab-btn";

    document.getElementById("content-subtab-rules").style.display = subtab === 'rules' ? 'block' : 'none';
    document.getElementById("content-subtab-media").style.display = subtab === 'media' ? 'block' : 'none';
    document.getElementById("content-subtab-faqs").style.display = subtab === 'faqs' ? 'block' : 'none';
    document.getElementById("content-subtab-comments").style.display = subtab === 'comments' ? 'block' : 'none';

    if (subtab === 'rules') loadTrainingRules();
    else if (subtab === 'media') loadSavedMediaList();
    else if (subtab === 'faqs') loadFaqs();
    else if (subtab === 'comments') loadCommentLogs();
}

// ------------------------------------------
// AI BRAIN TRAINING RULES MANAGER
// ------------------------------------------
async function loadTrainingRules() {
    const container = document.getElementById("training-rules-list-container");
    if (!container) return;

    try {
        const res = await fetch("/api/training/rules");
        const data = await res.json();
        container.innerHTML = "";

        if (!data.rules || data.rules.length === 0) {
            container.innerHTML = `<div style="padding: 24px; text-align: center; color: var(--text-muted);"><i class="fas fa-brain" style="font-size: 32px; opacity: 0.4; margin-bottom: 8px; display: block;"></i>কোনো কাস্টম ট্রেইনিং রুল যুক্ত করা হয়নি। নতুন রুল যুক্ত করতে উপরের বাটনে ক্লিক করুন।</div>`;
            return;
        }

        const grid = document.createElement("div");
        grid.style.cssText = "display: flex; flex-direction: column; gap: 12px;";

        data.rules.forEach(r => {
            const card = document.createElement("div");
            card.className = "glass-card";
            card.style.cssText = "padding: 14px 18px; margin: 0; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; border: 1px solid rgba(255,255,255,0.08);";
            
            const isActive = r.is_active === 1;
            const categoryBadge = `<span class="badge" style="background: rgba(99, 102, 241, 0.2); color: #818cf8; font-size: 11px;">${r.category || 'General'}</span>`;
            const typeBadge = `<span class="badge" style="background: rgba(236, 72, 153, 0.15); color: #f472b6; font-size: 10px; text-transform: uppercase;">${r.rule_type || 'Rule'}</span>`;

            card.innerHTML = `
                <div style="flex: 1;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                        <strong style="color: #fff; font-size: 14px;">${r.title}</strong>
                        ${categoryBadge}
                        ${typeBadge}
                    </div>
                    ${r.question_or_trigger ? `<div style="font-size: 12px; color: #fbbf24; margin-bottom: 4px;"><i class="fas fa-bolt"></i> <strong>Trigger:</strong> "${r.question_or_trigger}"</div>` : ''}
                    <div style="font-size: 13px; color: var(--text-main); line-height: 1.5; background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px; border-left: 3px solid ${isActive ? '#10b981' : '#6b7280'};">
                        ${r.response_or_rule}
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 10px; padding-top: 4px;">
                    <button class="btn" style="padding: 4px 10px; font-size: 11px; border-radius: 20px; ${isActive ? 'background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981;' : 'background: rgba(107, 114, 128, 0.2); color: #9ca3af; border: 1px solid #6b7280;'}" onclick="toggleTrainingRuleActive(${r.id})">
                        <i class="fas ${isActive ? 'fa-check-circle' : 'fa-circle-xmark'}"></i> ${isActive ? 'Active' : 'Disabled'}
                    </button>
                    <button class="btn btn-secondary" style="padding: 5px 8px; color: #ef4444;" onclick="deleteTrainingRuleById(${r.id})" title="Delete Rule">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
            grid.appendChild(card);
        });

        container.appendChild(grid);
    } catch (e) {
        console.error("Load training rules error:", e);
    }
}

async function handleCreateTrainingRule(e) {
    e.preventDefault();
    const title = document.getElementById("rule-title").value.trim();
    const category = document.getElementById("rule-category").value;
    const rule_type = document.getElementById("rule-type").value;
    const trigger = document.getElementById("rule-trigger").value.trim();
    const content = document.getElementById("rule-content").value.trim();

    if (!title || !content) return;

    try {
        const res = await fetch("/api/training/rules", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: title,
                category: category,
                rule_type: rule_type,
                question_or_trigger: trigger,
                response_or_rule: content,
                is_active: 1
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("এআই ট্রেইনিং রুল সফলভাবে যুক্ত হয়েছে!", "success");
            closeModal("modal-add-training-rule");
            document.getElementById("form-add-training-rule").reset();
            loadTrainingRules();
        }
    } catch (e) {
        showToast("রুল যুক্ত করা সম্ভব হয়নি", "danger");
    }
}

async function toggleTrainingRuleActive(ruleId) {
    try {
        await fetch(`/api/training/rules/${ruleId}/toggle`, { method: "POST" });
        loadTrainingRules();
        showToast("রুল স্ট্যাটাস আপডেট করা হয়েছে", "success");
    } catch (e) {
        showToast("Error updating status", "danger");
    }
}

async function deleteTrainingRuleById(ruleId) {
    if (!confirm("আপনি কি নিশ্চিত এই ট্রেইনিং রুলটি মুছে ফেলতে চান?")) return;
    try {
        await fetch(`/api/training/rules/${ruleId}`, { method: "DELETE" });
        loadTrainingRules();
        showToast("রুল ডিলিট সম্পন্ন হয়েছে", "success");
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ------------------------------------------
// SAVED MEDIA LIBRARY (VOICE & VIDEO)
// ------------------------------------------
async function loadSavedMediaList() {
    const container = document.getElementById("saved-media-grid");
    if (!container) return;

    try {
        const res = await fetch("/api/saved-media");
        const data = await res.json();
        container.innerHTML = "";

        if (!data.media || data.media.length === 0) {
            container.innerHTML = `<div style="grid-column: 1/-1; padding: 24px; text-align: center; color: var(--text-muted);"><i class="fas fa-photo-video" style="font-size: 32px; opacity: 0.4; margin-bottom: 8px; display: block;"></i>কোনো সেভ করা ভয়েস বা ভিডিও নেই। "Upload Voice / Video" বাটনে ক্লিক করে যুক্ত করুন।</div>`;
            return;
        }

        data.media.forEach(m => {
            const card = document.createElement("div");
            card.className = "glass-card";
            card.style.cssText = "padding: 14px; margin: 0; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid rgba(255,255,255,0.08);";

            const isVoice = m.media_type === 'voice';
            const isVideo = m.media_type === 'video';

            let previewHtml = "";
            if (isVoice) {
                previewHtml = `<audio controls style="width: 100%; margin: 8px 0; height: 36px;"><source src="${m.file_url}" type="audio/mpeg"></audio>`;
            } else if (isVideo) {
                previewHtml = `<video controls style="width: 100%; max-height: 140px; border-radius: 6px; margin: 8px 0; background: #000;"><source src="${m.file_url}" type="video/mp4"></video>`;
            } else {
                previewHtml = `<img src="${m.file_url}" style="width: 100%; height: 120px; object-fit: cover; border-radius: 6px; margin: 8px 0;">`;
            }

            card.innerHTML = `
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <strong style="color: #fff; font-size: 13px;">${m.title}</strong>
                        <span class="badge" style="font-size: 10px;">${isVoice ? '🎙️ Voice' : (isVideo ? '🎬 Video' : '🖼️ Photo')}</span>
                    </div>
                    ${m.description ? `<small style="color: var(--text-muted); display: block; margin-top: 4px;">${m.description}</small>` : ''}
                    ${previewHtml}
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06);">
                    <small style="color: var(--text-dim); font-size: 10px;">${m.created_at || ''}</small>
                    <button class="btn btn-secondary" style="padding: 4px 8px; color: #ef4444; font-size: 11px;" onclick="deleteSavedMediaById(${m.id})">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error("Load saved media error:", e);
    }
}

async function handleUploadSavedMedia(e) {
    e.preventDefault();
    const title = document.getElementById("media-title").value.trim();
    const media_type = document.getElementById("media-type").value;
    const desc = document.getElementById("media-desc").value.trim();
    const fileInput = document.getElementById("media-file");

    if (!fileInput.files || fileInput.files.length === 0) {
        showToast("দয়া করে ফাইল সিলেক্ট করুন", "danger");
        return;
    }

    const formData = new FormData();
    formData.append("title", title);
    formData.append("media_type", media_type);
    formData.append("description", desc);
    formData.append("file", fileInput.files[0]);

    try {
        showToast("আপলোড হচ্ছে...", "info");
        const res = await fetch("/api/saved-media/upload", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("মিডিয়া সফলভাবে আপলোড হয়েছে!", "success");
            closeModal("modal-upload-media");
            document.getElementById("form-upload-media").reset();
            loadSavedMediaList();
        }
    } catch (e) {
        showToast("Upload failed", "danger");
    }
}

async function deleteSavedMediaById(mediaId) {
    if (!confirm("আপনি কি নিশ্চিত এই মিডিয়া ফাইলটি ডিলিট করতে চান?")) return;
    try {
        await fetch(`/api/saved-media/${mediaId}`, { method: "DELETE" });
        loadSavedMediaList();
        showToast("মিডিয়া ডিলিট সম্পন্ন হয়েছে", "success");
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ------------------------------------------
// QUICK MEDIA SEND IN OMNICHAT
// ------------------------------------------
let activeQuickMediaType = 'voice';

async function openQuickMediaModal(type) {
    activeQuickMediaType = type;
    const titleElem = document.getElementById("quick-media-modal-title");
    if (titleElem) {
        titleElem.innerHTML = type === 'voice' 
            ? '<i class="fas fa-microphone-lines" style="color:#ec4899;"></i> Send Saved Voice Note'
            : '<i class="fas fa-video" style="color:#3b82f6;"></i> Send Saved Product Demo Video';
    }

    const container = document.getElementById("quick-media-list-container");
    if (!container) return;

    try {
        container.innerHTML = `<div style="text-align: center; padding: 20px;"><i class="fas fa-spinner fa-spin"></i> Loading...</div>`;
        openModal("modal-quick-media");

        const res = await fetch(`/api/saved-media?type=${type}`);
        const data = await res.json();
        container.innerHTML = "";

        if (!data.media || data.media.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 25px; color: var(--text-muted);">
                    কোনো ${type === 'voice' ? 'ভয়েস নোট' : 'ভিডিও'} পাওয়া যায়নি।<br>
                    <button class="btn btn-primary" style="margin-top: 10px; font-size: 11px;" onclick="closeModal('modal-quick-media'); openModal('modal-upload-media');">
                        <i class="fas fa-upload"></i> Upload Now
                    </button>
                </div>
            `;
            return;
        }

        data.media.forEach(m => {
            const row = document.createElement("div");
            row.style.cssText = "padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; display: flex; justify-content: space-between; align-items: center; gap: 12px;";

            const preview = type === 'voice' 
                ? `<audio controls style="height: 32px; width: 180px;"><source src="${m.file_url}"></audio>`
                : `<video style="height: 40px; width: 60px; object-fit: cover; border-radius: 4px;" src="${m.file_url}"></video>`;

            row.innerHTML = `
                <div style="flex: 1;">
                    <strong style="color: #fff; font-size: 13px;">${m.title}</strong>
                    ${m.description ? `<small style="color: var(--text-muted); display: block;">${m.description}</small>` : ''}
                </div>
                <div>${preview}</div>
                <button class="btn btn-primary" style="padding: 6px 14px; font-size: 11px; white-space: nowrap;" onclick="sendSavedMediaToActiveChat(${m.id})">
                    <i class="fas fa-paper-plane"></i> Send
                </button>
            `;
            container.appendChild(row);
        });
    } catch (e) {
        console.error("Open quick media modal error:", e);
    }
}

async function sendSavedMediaToActiveChat(mediaId) {
    if (!activeConversationId) {
        showToast("Please select a conversation first", "warning");
        return;
    }

    try {
        showToast("Sending media to customer...", "info");
        const res = await fetch("/api/saved-media/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                conversation_id: activeConversationId,
                media_id: mediaId
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("মিডিয়া সফলভাবে কাস্টমারকে পাঠানো হয়েছে!", "success");
            closeModal("modal-quick-media");
            loadOmnichatMessages(activeConversationId);
            loadOmnichatConversations();
        } else {
            showToast(data.error || "Failed to send media", "danger");
        }
    } catch (e) {
        showToast("Send error", "danger");
    }
}

// ==========================================
// 7. OMNICHAT (INBOX)
// ==========================================
let activeConversationId = null;
let activeConversationsList = [];

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

        activeConversationsList = data.conversations;

        data.conversations.forEach((c, idx) => {
            const item = document.createElement("div");
            item.style.cssText = "padding: 12px 16px; border-bottom: 1px solid var(--border-color); cursor: pointer; transition: var(--transition);";
            if (activeConversationId === c.id || (idx === 0 && !activeConversationId)) {
                activeConversationId = c.id;
                item.style.background = "var(--primary-soft)";
                updateOmnichatHeader(c);
            }
            const isWhatsApp = (c.channel || '').toLowerCase() === 'whatsapp';
            const channelBadge = isWhatsApp
                ? `<span class="badge" style="background: rgba(37, 211, 102, 0.2); color: #25d366; font-size: 10px; font-weight: 600;"><i class="fab fa-whatsapp"></i> WhatsApp</span>`
                : `<span class="badge" style="background: rgba(24, 119, 242, 0.2); color: #60a5fa; font-size: 10px; font-weight: 600;"><i class="fab fa-facebook-messenger"></i> Messenger</span>`;

            const aiStatusIcon = c.human_takeover === 1 
                ? `<span title="AI Paused for this customer" style="color: #f59e0b; font-size: 10px; margin-left: 6px;"><i class="fas fa-pause-circle"></i> Owner Mode</span>` 
                : `<span title="AI Auto-Reply Active" style="color: #10b981; font-size: 10px; margin-left: 6px;"><i class="fas fa-robot"></i> AI Active</span>`;

            item.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <strong style="color: #fff; font-size: 13.5px;">${c.customer_name || 'Customer'}</strong>
                    <div>${channelBadge}</div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--text-muted);">
                    <span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px;">${c.last_message || ''}</span>
                    ${aiStatusIcon}
                </div>
            `;
            item.addEventListener("click", () => {
                activeConversationId = c.id;
                document.querySelectorAll("#omnichat-threads-list > div").forEach(d => d.style.background = "transparent");
                item.style.background = "var(--primary-soft)";
                updateOmnichatHeader(c);
                loadOmnichatMessages(c.id);
            });
            container.appendChild(item);
        });

        if (activeConversationId) loadOmnichatMessages(activeConversationId);
    } catch (e) {
        console.error("Load Omnichat conversations error:", e);
    }
}

function updateOmnichatHeader(c) {
    if (!c) return;
    const nameElem = document.getElementById("omnichat-active-customer-name");
    const badgeElem = document.getElementById("omnichat-active-channel-badge");
    const aiBtn = document.getElementById("omnichat-ai-toggle-btn");
    const aiText = document.getElementById("omnichat-ai-toggle-text");

    if (nameElem) nameElem.innerText = c.customer_name || 'Customer';
    if (badgeElem) {
        badgeElem.innerText = (c.channel || 'whatsapp').toUpperCase();
        badgeElem.className = (c.channel === 'whatsapp') ? 'badge badge-confirmed' : 'badge badge-shipped';
    }

    if (aiBtn && aiText) {
        if (c.human_takeover === 1) {
            aiBtn.style.background = "rgba(245, 158, 11, 0.2)";
            aiBtn.style.border = "1px solid #f59e0b";
            aiBtn.style.color = "#fbbf24";
            aiText.innerText = "AI Paused (Owner Mode)";
            aiBtn.title = "Click to resume AI auto-reply for this customer";
        } else {
            aiBtn.style.background = "rgba(16, 185, 129, 0.15)";
            aiBtn.style.border = "1px solid #10b981";
            aiBtn.style.color = "#34d399";
            aiText.innerText = "AI Active";
            aiBtn.title = "Click to pause AI (take over conversation manually)";
        }
    }
}

async function toggleActiveChatAI() {
    if (!activeConversationId) return;

    try {
        const res = await fetch("/api/omnichat/toggle-ai", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ conversation_id: activeConversationId })
        });
        const data = await res.json();
        if (data.success) {
            const isPaused = data.human_takeover === 1;
            showToast(isPaused ? "এই কাস্টমারের জন্য এআই সাময়িকভাবে বন্ধ করা হয়েছে (Owner Mode)" : "এই কাস্টমারের জন্য এআই স্বয়ংক্রিয় উত্তর পুনরায় চালু করা হয়েছে (AI Active)", "info");
            loadOmnichatConversations();
        }
    } catch (e) {
        showToast("Failed to toggle AI status", "danger");
    }
}

async function loadOmnichatMessages(cid) {
    const container = document.getElementById("omnichat-messages-container");
    if (!container || !cid) return;

    try {
        const res = await fetch(`/api/omnichat/messages/${cid}`);
        const data = await res.json();

        container.innerHTML = "";
        data.messages.forEach(m => {
            const div = document.createElement("div");
            div.className = `message-bubble ${m.sender_type === 'user' ? 'message-user' : 'message-bot'}`;
            
            let html = "";
            if (m.content) {
                let formatted = m.content;
                // Render any markdown images as beautiful image cards
                formatted = formatted.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, src) => {
                    return `<div style="margin: 6px 0;"><img src="${src}" alt="${alt || 'Image'}" style="max-width: 220px; max-height: 180px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); display: block;"></div>`;
                });
                html += `<div>${formatted.replace(/\n/g, "<br>")}</div>`;
            }
            if (m.media_url) {
                if (m.message_type === 'voice' || m.message_type === 'audio') {
                    html += `<div style="margin-top: 6px;"><audio controls style="height: 32px; max-width: 240px;"><source src="${m.media_url}"></audio></div>`;
                } else if (m.message_type === 'video') {
                    html += `<div style="margin-top: 6px;"><video controls style="max-width: 240px; max-height: 180px; border-radius: 8px;"><source src="${m.media_url}"></video></div>`;
                } else {
                    html += `<div style="margin-top: 6px;"><img src="${m.media_url}" style="max-width: 220px; max-height: 180px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1);"></div>`;
                }
            }
            div.innerHTML = html;
            container.appendChild(div);
        });
        container.scrollTop = container.scrollHeight;
    } catch (e) {
        console.error("Load Omnichat messages error:", e);
    }
}

// Auto-poll Omnichat every 4 seconds for real-time live chat updates
setInterval(() => {
    const omnichatTab = document.getElementById("tab-omnichat");
    if (omnichatTab && omnichatTab.classList.contains("active")) {
        loadOmnichatConversations();
    }
}, 4000);

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
            showToast("Message sent to customer", "success");
        } else {
            showToast(data.error || "Failed to send message via WhatsApp Cloud API", "danger");
        }
    } catch (e) {
        showToast("Send failed: Server error", "danger");
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

        const fbToken = s.fb_page_access_token || "";
        const waToken = s.whatsapp_access_token || s.meta_system_user_access_token || "";
        const waStatus = s.whatsapp_connection_status || "connected";

        if (document.getElementById("setting-fb-token")) document.getElementById("setting-fb-token").value = fbToken;
        if (document.getElementById("setting-fb-page-id")) document.getElementById("setting-fb-page-id").value = s.fb_page_id || "";
        if (document.getElementById("setting-fb-app-secret")) document.getElementById("setting-fb-app-secret").value = s.fb_app_secret || "";

        if (document.getElementById("setting-wa-waba-id")) document.getElementById("setting-wa-waba-id").value = s.whatsapp_waba_id || "";
        if (document.getElementById("setting-wa-phone-id")) document.getElementById("setting-wa-phone-id").value = s.whatsapp_phone_number_id || "";
        if (document.getElementById("setting-wa-token")) document.getElementById("setting-wa-token").value = waToken;

        if (document.getElementById("setting-gemini-key")) document.getElementById("setting-gemini-key").value = s.gemini_api_key || "";
        if (document.getElementById("setting-shop-name")) document.getElementById("setting-shop-name").value = s.shop_name || "RS Graphics";
        if (document.getElementById("setting-shop-phone")) document.getElementById("setting-shop-phone").value = s.shop_phone || "";
        if (document.getElementById("setting-delivery-inside")) document.getElementById("setting-delivery-inside").value = s.delivery_inside_dhaka || "70";
        if (document.getElementById("setting-delivery-outside")) document.getElementById("setting-delivery-outside").value = s.delivery_outside_dhaka || "130";
        if (document.getElementById("setting-comment-reply-template")) document.getElementById("setting-comment-reply-template").value = s.comment_reply_template || "";

        // Display WhatsApp connection details
        const isWaConnected = (
            s.whatsapp_connection_status === "connected" 
            && s.whatsapp_phone_number_id 
            && s.whatsapp_phone_number_id !== "1265595526643418"
        );

        if (document.getElementById("wa-display-phone")) {
            document.getElementById("wa-display-phone").innerHTML = `<i class="fas fa-phone-alt" style="color: #25d366; font-size: 12px;"></i> +8801816504097`;
        }
        if (document.getElementById("wa-display-waba-id")) {
            document.getElementById("wa-display-waba-id").innerText = s.whatsapp_waba_id || "27905447135785944";
        }
        if (document.getElementById("wa-display-phone-id")) {
            document.getElementById("wa-display-phone-id").innerText = isWaConnected ? s.whatsapp_phone_number_id : "Awaiting Meta verification";
        }

        // Update Facebook Connection Badge
        const fbBadge = document.getElementById("fb-status-badge");
        if (fbBadge) {
            if (s.fb_token_configured || (fbToken && fbToken.trim().length > 5)) {
                fbBadge.className = "badge badge-confirmed";
                fbBadge.innerHTML = `<i class="fas fa-check-circle"></i> Connected & Saved`;
            } else {
                fbBadge.className = "badge badge-pending";
                fbBadge.innerText = "Ready to Connect";
            }
        }

        // Update WhatsApp Connection Badge
        const waBadge = document.getElementById("wa-status-badge");
        if (waBadge) {
            if (isWaConnected) {
                waBadge.className = "badge badge-confirmed";
                waBadge.innerHTML = `<i class="fas fa-check-circle"></i> Connected & Saved (Coexistence Active)`;
            } else if (s.whatsapp_connection_status === "pending") {
                waBadge.className = "badge badge-pending";
                waBadge.innerText = "Verification Pending in Meta";
            } else {
                waBadge.className = "badge badge-pending";
                waBadge.innerHTML = `<i class="fas fa-circle-notch"></i> Ready to Connect (+8801816504097)`;
            }
        }

        // Dynamic Webhook URLs based on current origin
        const currentOrigin = window.location.origin;
        if (document.getElementById("setting-fb-webhook-display")) {
            document.getElementById("setting-fb-webhook-display").value = `${currentOrigin}/webhook/facebook`;
        }
        if (document.getElementById("setting-wa-webhook-display")) {
            document.getElementById("setting-wa-webhook-display").value = `${currentOrigin}/webhook/whatsapp`;
        }

        // AI Arena Setup tab inputs
        if (document.getElementById("arena-shop-name")) document.getElementById("arena-shop-name").value = s.shop_name || "RS Graphics";
        if (document.getElementById("arena-system-prompt")) document.getElementById("arena-system-prompt").value = s.ai_system_prompt || "";
        if (document.getElementById("phone-header-shop-name")) document.getElementById("phone-header-shop-name").innerText = s.shop_name || "RS Graphics";

    } catch (e) {
        console.error("Load settings error:", e);
    }
}

async function disconnectWhatsApp() {
    if (!confirm("Are you sure you want to reset WhatsApp Business connection status?")) return;
    try {
        const res = await fetch("/api/whatsapp/disconnect", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("WhatsApp connection reset", "info");
            loadSettings();
        }
    } catch (e) {
        showToast("Failed to disconnect", "danger");
    }
}

// Meta Embedded Signup for WhatsApp Business App Coexistence
console.log("[WA EMBEDDED SIGNUP VERSION] 2026-08-20-IMAGEFIX");
let metaSDKInitialized = false;
let embeddedSignupSessionInfo = null;

// Listen for WhatsApp Embedded Signup message events from Meta
window.addEventListener('message', (event) => {
    if (event.origin !== "https://www.facebook.com" && event.origin !== "https://web.facebook.com") return;
    try {
        const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
        if (data && (data.type === 'WA_EMBEDDED_SIGNUP' || data.event === 'FINISH' || data.event === 'COMPLETE')) {
            console.log('[WhatsApp Embedded Signup] Session Info Event received');
            embeddedSignupSessionInfo = data.data || data;
            const phoneId = embeddedSignupSessionInfo.phone_number_id || embeddedSignupSessionInfo.phoneNumberId;
            const wabaId = embeddedSignupSessionInfo.waba_id || embeddedSignupSessionInfo.wabaId;
            if (phoneId) console.log('[WA DEBUG] Phone Number ID received:', phoneId);
            if (wabaId) console.log('[WA DEBUG] WABA ID received:', wabaId);
        }
    } catch (e) {}
});

async function initMetaSDK(targetAppId) {
    const appId = String(targetAppId || "1274136137801052").trim();

    if (window.FB) {
        try {
            FB.init({
                appId: appId,
                cookie: true,
                xfbml: true,
                version: "v19.0"
            });
            metaSDKInitialized = true;
            return;
        } catch (e) {}
    }

    return new Promise((resolve) => {
        window.fbAsyncInit = function() {
            FB.init({
                appId: appId,
                cookie: true,
                xfbml: true,
                version: "v19.0"
            });
            metaSDKInitialized = true;
            resolve();
        };

        if (!document.getElementById("facebook-jssdk")) {
            const js = document.createElement("script");
            js.id = "facebook-jssdk";
            js.src = "https://connect.facebook.net/en_US/sdk.js";
            document.head.appendChild(js);
        } else {
            let checks = 0;
            const interval = setInterval(() => {
                checks++;
                if (window.FB) {
                    clearInterval(interval);
                    FB.init({
                        appId: appId,
                        cookie: true,
                        xfbml: true,
                        version: "v19.0"
                    });
                    metaSDKInitialized = true;
                    resolve();
                } else if (checks > 40) {
                    clearInterval(interval);
                    resolve();
                }
            }, 100);
        }
    });
}

async function launchWhatsAppEmbeddedSignup() {
    showToast("Connecting to Meta WhatsApp Business...", "info");

    try {
        const res = await fetch("/api/whatsapp/embedded-config");
        const config = await res.json();
        let rawId = String(config.config_id || "1003403176086013").trim();
        const configId = (rawId === "10034031760860138") ? "1003403176086013" : rawId;
        const appId = String(config.app_id || "1274136137801052").trim();

        if (!configId || configId.length === 0) {
            showToast("Meta Embedded Signup configuration missing. Please check META_EMBEDDED_SIGNUP_CONFIG_ID in Render.", "warning");
            const manualDetails = document.querySelector("#tab-integrations details");
            if (manualDetails) manualDetails.open = true;
            return;
        }

        await initMetaSDK(appId);

        if (!window.FB) {
            showToast("Meta SDK could not be loaded. Please check your network connection.", "danger");
            return;
        }

        const loginOptions = {
            config_id: configId,
            response_type: "code",
            override_default_response_type: true,
            extras: {
                setup: {},
                featureType: "whatsapp_business_app_onboarding",
                sessionInfoVersion: "3"
            }
        };

        console.log("[WA DEBUG] appId =", appId);
        console.log("[WA DEBUG] configId =", configId);
        console.log("[WA DEBUG] configId length =", configId.length);
        console.log("[WA DEBUG] loginOptions =", loginOptions);

        FB.login((response) => {
            console.log("[WA DEBUG] Meta login response:", response);
            if (response && response.authResponse && response.authResponse.code) {
                console.log("[WA DEBUG] authorization code received: YES");
                const code = response.authResponse.code;
                const sessionData = embeddedSignupSessionInfo || {};
                const wabaId = sessionData.waba_id || sessionData.wabaId || null;
                const phoneId = sessionData.phone_number_id || sessionData.phoneNumberId || null;
                const displayPhone = sessionData.display_phone_number || sessionData.displayPhoneNumber || '01816504097';

                if (wabaId) console.log("[WA DEBUG] WABA ID:", wabaId);
                if (phoneId) console.log("[WA DEBUG] Phone Number ID:", phoneId);

                fetch("/api/whatsapp/embedded-signup", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        code: code,
                        waba_id: wabaId,
                        phone_number_id: phoneId,
                        display_phone_number: displayPhone
                    })
                }).then(r => r.json()).then(result => {
                    console.log("[WA DEBUG] backend callback result:", result);
                    if (result && result.success) {
                        showToast("✅ WhatsApp Business App Connected (Coexistence Mode Active)!", "success");
                        loadSettings();
                    } else {
                        console.error("[WhatsApp Embedded Signup] Connection failed:", result);
                        showToast(result.message || "Embedded Signup failed", "danger");
                    }
                }).catch(err => {
                    console.error("[WhatsApp Embedded Signup] API error:", err);
                    showToast("Failed to save connection on server", "danger");
                });
            } else if (response && response.status === 'not_authorized') {
                console.warn("[WA DEBUG] Meta login not authorized");
                showToast("Meta login not authorized or cancelled", "warning");
            } else {
                console.log("[WA DEBUG] WhatsApp connection was cancelled or closed");
                showToast("WhatsApp connection was cancelled.", "warning");
            }
        }, loginOptions);

    } catch (err) {
        console.error("[WhatsApp Embedded Signup] Launch Error:", err);
        showToast("Failed to launch Meta Embedded Signup", "danger");
    }
}

function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === "password") {
        input.type = "text";
        if (btn) btn.innerHTML = `<i class="fas fa-eye-slash" style="color: var(--primary-light);"></i>`;
    } else {
        input.type = "password";
        if (btn) btn.innerHTML = `<i class="fas fa-eye"></i>`;
    }
}

function updateAIMasterButtonUI(active) {
    const btn = document.getElementById("ai-master-toggle-btn");
    const text = document.getElementById("ai-master-status-text");
    const mobileBtn = document.getElementById("mobile-ai-master-btn");
    const mobileText = document.getElementById("mobile-ai-master-text");

    if (btn) {
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

    if (mobileBtn) {
        if (active) {
            mobileBtn.style.background = "rgba(16, 185, 129, 0.15)";
            mobileBtn.style.borderColor = "#10b981";
            mobileBtn.style.color = "#34d399";
            mobileBtn.innerHTML = `<i class="fas fa-circle" style="font-size: 7px;"></i> <span id="mobile-ai-master-text">Active</span>`;
        } else {
            mobileBtn.style.background = "rgba(239, 68, 68, 0.15)";
            mobileBtn.style.borderColor = "#ef4444";
            mobileBtn.style.color = "#f87171";
            mobileBtn.innerHTML = `<i class="fas fa-pause-circle" style="font-size: 8px;"></i> <span id="mobile-ai-master-text">Paused</span>`;
        }
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

async function saveFacebookSettings() {
    const token = document.getElementById("setting-fb-token") ? document.getElementById("setting-fb-token").value.trim() : "";
    if (!token) {
        showToast("দয়া করে Facebook Page Access Token-টি পেস্ট করুন", "warning");
        return;
    }

    if (token.includes("...")) {
        showToast("Token is already configured securely.", "info");
        return;
    }

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fb_page_access_token: token })
        });
        const data = await res.json();
        if (data.success) {
            showToast("✅ Facebook Page Access Token সফলভাবে সংরক্ষিত হয়েছে!", "success");
            loadSettings();
        }
    } catch (e) {
        showToast("Failed to save Facebook token", "danger");
    }
}

async function saveWhatsAppSettings() {
    const wabaId = document.getElementById("setting-wa-waba-id") ? document.getElementById("setting-wa-waba-id").value.trim() : "";
    const phoneId = document.getElementById("setting-wa-phone-id") ? document.getElementById("setting-wa-phone-id").value.trim() : "";
    const token = document.getElementById("setting-wa-token") ? document.getElementById("setting-wa-token").value.trim() : "";

    const payload = {};
    if (wabaId) payload.whatsapp_waba_id = wabaId;
    if (phoneId) payload.whatsapp_phone_number_id = phoneId;
    if (token && !token.includes("...")) payload.whatsapp_access_token = token;
    payload.whatsapp_connection_mode = "business_app_coexistence";

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("✅ WhatsApp Settings সফলভাবে সংরক্ষিত হয়েছে!", "success");
            loadSettings();
        }
    } catch (e) {
        showToast("Failed to save WhatsApp settings", "danger");
    }
}

async function saveAllSettings(e) {
    if (e) e.preventDefault();
    const payload = {
        shop_name: document.getElementById("setting-shop-name") ? document.getElementById("setting-shop-name").value : "আমার ই-কমার্স শপ",
        shop_phone: document.getElementById("setting-shop-phone") ? document.getElementById("setting-shop-phone").value : "01700000000",
        delivery_inside_dhaka: document.getElementById("setting-delivery-inside") ? document.getElementById("setting-delivery-inside").value : "70",
        delivery_outside_dhaka: document.getElementById("setting-delivery-outside") ? document.getElementById("setting-delivery-outside").value : "130"
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
        let formatted = text;
        formatted = formatted.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, src) => {
            return `<div style="margin: 6px 0;"><img src="${src}" alt="${alt || 'Image'}" style="max-width: 100%; max-height: 180px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); display: block;"></div>`;
        });
        html += `<div>${formatted.replace(/\n/g, "<br>")}</div>`;
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
