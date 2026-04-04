# Backend Apps Arxitekturasi V2

## Maqsad

`admin-frontend` va `pos-frontend` dagi modullar ancha aniq bounded-context bo'yicha ajralgan:

- `admin-frontend`: `product-owner`, `business-partner`, `restaurant-admin`, `user-management`
- `pos-frontend`: `auth`, `waiter`, `cashier`, `kitchen`

Hozirgi backend esa ko'proq model-markaziy va transport-gateway usulida qurilgan:

- `apps.admin` bir nechta domainni bitta HTTP qatlamga yig'ib yuborgan
- `apps.accounts` ichida auth, ACL, employee profile va POS session aralashib ketgan
- `apps.organizations` ichida platform darajasi va restaurant constructor resurslari aralash
- `apps.orders` ichida cashier, order, payment, receipt va shift use-case'lari bitta joyga yig'ilgan
- `apps.dashboard` va `apps.reports` o'rtasida javobgarlik ajralishi noaniq

Shu sabab yangi arxitektura frontend modullari va real business capability'lar bo'yicha qurilishi kerak.

## Asosiy qoidalar

1. `apps.admin` alohida Django app sifatida qolmaydi.
2. Har bir Django app bitta business capability'ga egalik qiladi.
3. Har bir app ichida HTTP surface `api/admin` va `api/pos` bo'yicha ajratiladi.
4. ORM modellari appga tegishli bo'ladi, boshqa app ularni faqat service yoki selector orqali ishlatadi.
5. Write use-case'lar `services/`, read use-case'lar `selectors/` ichida bo'ladi.
6. Reportlar write model emas, alohida read-oriented app bo'ladi.
7. `constructor`, `platform`, `operations` kabi texnik nomlar URL darajasida kamaytiriladi; resource nomlari asosiy bo'ladi.

## Tavsiya etilgan root apps

```text
apps/
  iam/
    api/
      admin/
        urls.py
        views/
        serializers/
      pos/
        urls.py
        views/
        serializers/
    models/
    permissions/
    selectors/
    services/
    tests/

  platform/
    api/
      admin/
        urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/

  restaurants/
    api/
      admin/
        urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/

  staffing/
    api/
      admin/
        urls.py
        views/
        serializers/
      pos/
        urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/

  catalog/
    api/
      admin/
        urls.py
        views/
        serializers/
      pos/
        urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/

  floor/
    api/
      admin/
        urls.py
        views/
        serializers/
      pos/
        urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/

  sales/
    api/
      admin/
        urls.py
        views/
        serializers/
      pos/
        cashier_urls.py
        sales_urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/

  kitchen/
    api/
      admin/
        urls.py
        views/
        serializers/
      pos/
        urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/

  reporting/
    api/
      admin/
        urls.py
        views/
        serializers/
    selectors/
    services/
    tests/

  integrations/
    api/
      admin/
        urls.py
        views/
        serializers/
    models/
    selectors/
    services/
    tests/
```

`common/` va `core/` infra qatlam sifatida qoladi.

## Qaysi model qayerga ko'chadi

| Yangi app | Mas'uliyat | Hozirgi manba |
| --- | --- | --- |
| `iam` | `User`, `Role`, `Permission`, auth session, admin auth, POS auth | `apps.accounts`, qisman `apps.dashboard` |
| `platform` | `BusinessPartner`, `Tariff`, `RestaurantEntitlement`, partner lifecycle policy | `apps.organizations`, `apps.admin.product_owner`, `apps.admin.business_partner` |
| `restaurants` | `Restaurant`, `FeatureConfig`, `CashDesk`, `Device`, `PrepStation`, `DistributionPoint` | `apps.organizations`, `apps.admin.constructor` |
| `staffing` | employee va restaurantga bog'liq user profillar, employee API'lari | `apps.accounts` profil modellari, `apps.admin.users`ning employee qismi |
| `catalog` | category, item, mxik, POS menu | `apps.catalog`, `apps.admin.catalog` |
| `floor` | hall, zone, table, table session, reserve/move/merge | `apps.floor`, `apps.admin.constructor`, `apps.admin.hall_constructor` |
| `sales` | cash shift, order, order item, order item note, payment, refund, receipt, open checks | `apps.orders`, `apps.admin.orders` |
| `kitchen` | kitchen ticket va status oqimlari | `apps.kitchen`, `apps.admin.kitchen` |
| `reporting` | summary, sales, open checks, top items, top staff, payment breakdown, shifts, dashboard overview | `apps.reports`, qisman `apps.dashboard`, `apps.admin.reports` |
| `integrations` | integration config va tashqi adapterlar | `apps.integrations`, `apps.admin.integrations` |

## Nima yo'qoladi

- `apps.admin` alohida gateway-app sifatida yo'qoladi
- `apps.dashboard` alohida app sifatida reporting yoki `iam` ichiga singadi
- `constructor` URL prefiksi yo'qoladi
- `platform` prefiksi faqat platformga tegishli resource'lar uchun qoladi yoki butunlay olib tashlanadi

## Tavsiya etilgan `core/urls.py` target sxema

```python
from django.urls import include, path

from common.constants import API_V1_PREFIX

urlpatterns = [
    path(f"{API_V1_PREFIX}admin/auth/", include("apps.iam.api.admin.auth_urls")),
    path(f"{API_V1_PREFIX}admin/access/", include("apps.iam.api.admin.access_urls")),
    path(f"{API_V1_PREFIX}admin/business-partners/", include("apps.platform.api.admin.business_partner_urls")),
    path(f"{API_V1_PREFIX}admin/tariffs/", include("apps.platform.api.admin.tariff_urls")),
    path(f"{API_V1_PREFIX}admin/restaurants/", include("apps.restaurants.api.admin.urls")),
    path(f"{API_V1_PREFIX}admin/staff/", include("apps.staffing.api.admin.urls")),
    path(f"{API_V1_PREFIX}admin/catalog/", include("apps.catalog.api.admin.urls")),
    path(f"{API_V1_PREFIX}admin/floor/", include("apps.floor.api.admin.urls")),
    path(f"{API_V1_PREFIX}admin/sales/", include("apps.sales.api.admin.urls")),
    path(f"{API_V1_PREFIX}admin/kitchen/", include("apps.kitchen.api.admin.urls")),
    path(f"{API_V1_PREFIX}admin/reports/", include("apps.reporting.api.admin.urls")),
    path(f"{API_V1_PREFIX}admin/integrations/", include("apps.integrations.api.admin.urls")),
    path(f"{API_V1_PREFIX}pos/auth/", include("apps.iam.api.pos.auth_urls")),
    path(f"{API_V1_PREFIX}pos/catalog/", include("apps.catalog.api.pos.urls")),
    path(f"{API_V1_PREFIX}pos/floor/", include("apps.floor.api.pos.urls")),
    path(f"{API_V1_PREFIX}pos/cashier/", include("apps.sales.api.pos.cashier_urls")),
    path(f"{API_V1_PREFIX}pos/sales/", include("apps.sales.api.pos.sales_urls")),
    path(f"{API_V1_PREFIX}pos/kitchen/", include("apps.kitchen.api.pos.urls")),
]
```

## Canonical admin URL daraxti

### `iam`

- `POST /api/v1/admin/auth/login/`
- `POST /api/v1/admin/auth/logout/`
- `GET /api/v1/admin/auth/me/`
- `GET /api/v1/admin/access/users/`
- `POST /api/v1/admin/access/users/`
- `GET /api/v1/admin/access/users/{id}/`
- `PUT /api/v1/admin/access/users/{id}/`
- `GET /api/v1/admin/access/roles/`
- `POST /api/v1/admin/access/roles/`
- `GET /api/v1/admin/access/roles/{id}/`
- `PUT /api/v1/admin/access/roles/{id}/`
- `DELETE /api/v1/admin/access/roles/{id}/`
- `GET /api/v1/admin/access/permissions/`
- `GET /api/v1/admin/access/permissions/options/`

### `platform`

- `GET /api/v1/admin/business-partners/`
- `POST /api/v1/admin/business-partners/`
- `GET /api/v1/admin/business-partners/lookup/`
- `GET /api/v1/admin/business-partners/{id}/`
- `PUT /api/v1/admin/business-partners/{id}/`
- `POST /api/v1/admin/business-partners/{id}/activate/`
- `POST /api/v1/admin/business-partners/{id}/deactivate/`
- `POST /api/v1/admin/business-partners/{id}/reset-password/`
- `GET /api/v1/admin/tariffs/`
- `POST /api/v1/admin/tariffs/`
- `GET /api/v1/admin/tariff-options/`
- `GET /api/v1/admin/tariffs/{id}/`
- `PUT /api/v1/admin/tariffs/{id}/`

### `restaurants`

- `GET /api/v1/admin/restaurants/`
- `POST /api/v1/admin/restaurants/`
- `GET /api/v1/admin/restaurants/{id}/`
- `PUT /api/v1/admin/restaurants/{id}/`
- `DELETE /api/v1/admin/restaurants/{id}/`
- `GET /api/v1/admin/restaurants/{id}/feature-config/`
- `PUT /api/v1/admin/restaurants/{id}/feature-config/`
- `POST /api/v1/admin/restaurants/{id}/activate/`
- `POST /api/v1/admin/restaurants/{id}/deactivate/`
- `POST /api/v1/admin/restaurants/{id}/reset-password/`
- `GET /api/v1/admin/restaurants/current/`
- `PUT /api/v1/admin/restaurants/current/`
- `GET /api/v1/admin/restaurants/current/feature-config/`
- `PUT /api/v1/admin/restaurants/current/feature-config/`
- `GET /api/v1/admin/restaurants/current/cash-desks/`
- `POST /api/v1/admin/restaurants/current/cash-desks/`
- `GET /api/v1/admin/restaurants/current/cash-desks/{id}/`
- `PUT /api/v1/admin/restaurants/current/cash-desks/{id}/`
- `DELETE /api/v1/admin/restaurants/current/cash-desks/{id}/`
- `GET /api/v1/admin/restaurants/current/devices/`
- `POST /api/v1/admin/restaurants/current/devices/`
- `GET /api/v1/admin/restaurants/current/devices/{id}/`
- `PUT /api/v1/admin/restaurants/current/devices/{id}/`
- `DELETE /api/v1/admin/restaurants/current/devices/{id}/`
- `GET /api/v1/admin/restaurants/current/prep-stations/`
- `POST /api/v1/admin/restaurants/current/prep-stations/`
- `GET /api/v1/admin/restaurants/current/prep-stations/{id}/`
- `PUT /api/v1/admin/restaurants/current/prep-stations/{id}/`
- `DELETE /api/v1/admin/restaurants/current/prep-stations/{id}/`
- `GET /api/v1/admin/restaurants/current/distribution-points/`
- `POST /api/v1/admin/restaurants/current/distribution-points/`
- `GET /api/v1/admin/restaurants/current/distribution-points/{id}/`
- `PUT /api/v1/admin/restaurants/current/distribution-points/{id}/`
- `DELETE /api/v1/admin/restaurants/current/distribution-points/{id}/`

### `staffing`

- `GET /api/v1/admin/staff/employees/`
- `POST /api/v1/admin/staff/employees/`
- `GET /api/v1/admin/staff/employees/roles/`
- `GET /api/v1/admin/staff/employees/{id}/`
- `PUT /api/v1/admin/staff/employees/{id}/`

### `catalog`

- `GET /api/v1/admin/catalog/categories/`
- `POST /api/v1/admin/catalog/categories/`
- `GET /api/v1/admin/catalog/categories/{id}/`
- `PUT /api/v1/admin/catalog/categories/{id}/`
- `DELETE /api/v1/admin/catalog/categories/{id}/`
- `GET /api/v1/admin/catalog/items/`
- `POST /api/v1/admin/catalog/items/`
- `GET /api/v1/admin/catalog/items/{id}/`
- `PUT /api/v1/admin/catalog/items/{id}/`
- `DELETE /api/v1/admin/catalog/items/{id}/`
- `POST /api/v1/admin/catalog/items/{id}/stoplist/`
- `GET /api/v1/admin/catalog/mxik/search/`
- `GET /api/v1/admin/catalog/mxik/{code}/`

### `floor`

- `GET /api/v1/admin/floor/halls/`
- `POST /api/v1/admin/floor/halls/`
- `GET /api/v1/admin/floor/halls/{id}/`
- `PUT /api/v1/admin/floor/halls/{id}/`
- `DELETE /api/v1/admin/floor/halls/{id}/`
- `GET /api/v1/admin/floor/halls/{id}/constructor/`
- `PUT /api/v1/admin/floor/halls/{id}/constructor/`
- `GET /api/v1/admin/floor/zones/`
- `POST /api/v1/admin/floor/zones/`
- `GET /api/v1/admin/floor/zones/{id}/`
- `PUT /api/v1/admin/floor/zones/{id}/`
- `DELETE /api/v1/admin/floor/zones/{id}/`
- `GET /api/v1/admin/floor/tables/`
- `POST /api/v1/admin/floor/tables/`
- `GET /api/v1/admin/floor/tables/{id}/`
- `PUT /api/v1/admin/floor/tables/{id}/`
- `DELETE /api/v1/admin/floor/tables/{id}/`
- `GET /api/v1/admin/floor/table-sessions/`
- `POST /api/v1/admin/floor/table-sessions/`
- `GET /api/v1/admin/floor/table-sessions/{id}/`
- `PUT /api/v1/admin/floor/table-sessions/{id}/`
- `DELETE /api/v1/admin/floor/table-sessions/{id}/`

### `sales`

- `GET /api/v1/admin/sales/orders/`
- `GET /api/v1/admin/sales/orders/{id}/`
- `GET /api/v1/admin/sales/order-items/`
- `GET /api/v1/admin/sales/order-items/{id}/`
- `GET /api/v1/admin/sales/order-item-notes/`
- `GET /api/v1/admin/sales/order-item-notes/{id}/`
- `GET /api/v1/admin/sales/payments/`
- `GET /api/v1/admin/sales/payments/{id}/`
- `GET /api/v1/admin/sales/receipts/`
- `GET /api/v1/admin/sales/receipts/{id}/`

### `kitchen`

- `GET /api/v1/admin/kitchen/tickets/`
- `GET /api/v1/admin/kitchen/tickets/{id}/`

### `reporting`

- `GET /api/v1/admin/reports/summary/`
- `GET /api/v1/admin/reports/summary/export/`
- `GET /api/v1/admin/reports/sales/`
- `GET /api/v1/admin/reports/sales/export/`
- `GET /api/v1/admin/reports/open-checks/`
- `GET /api/v1/admin/reports/open-checks/export/`
- `GET /api/v1/admin/reports/top-items/`
- `GET /api/v1/admin/reports/top-items/export/`
- `GET /api/v1/admin/reports/top-staff/`
- `GET /api/v1/admin/reports/top-staff/export/`
- `GET /api/v1/admin/reports/payment-breakdown/`
- `GET /api/v1/admin/reports/payment-breakdown/export/`
- `GET /api/v1/admin/reports/shifts/`
- `GET /api/v1/admin/reports/shifts/export/`

### `integrations`

- `GET /api/v1/admin/integrations/configs/`
- `POST /api/v1/admin/integrations/configs/`
- `GET /api/v1/admin/integrations/configs/{id}/`
- `PUT /api/v1/admin/integrations/configs/{id}/`
- `DELETE /api/v1/admin/integrations/configs/{id}/`

## Canonical POS URL daraxti

### `iam`

- `POST /api/v1/pos/auth/restaurant-code/`
- `POST /api/v1/pos/auth/pin-login/`
- `POST /api/v1/pos/auth/logout/`
- `GET /api/v1/pos/auth/me/`

### `catalog`

- `GET /api/v1/pos/catalog/menu/`

### `floor`

- `GET /api/v1/pos/floor/halls/`
- `POST /api/v1/pos/floor/tables/{id}/reserve/`
- `GET /api/v1/pos/floor/table-sessions/{id}/`
- `POST /api/v1/pos/floor/table-sessions/`
- `POST /api/v1/pos/floor/table-sessions/{id}/move/`
- `POST /api/v1/pos/floor/table-sessions/{id}/merge/`

### `sales`

- `GET /api/v1/pos/cashier/context/`
- `POST /api/v1/pos/cashier/shifts/open/`
- `POST /api/v1/pos/cashier/shifts/current/close/`
- `GET /api/v1/pos/sales/orders/`
- `POST /api/v1/pos/sales/orders/`
- `GET /api/v1/pos/sales/orders/{id}/`
- `POST /api/v1/pos/sales/orders/{order_id}/items/`
- `DELETE /api/v1/pos/sales/order-items/{id}/`
- `POST /api/v1/pos/sales/orders/{id}/submit/`
- `GET /api/v1/pos/sales/open-checks/`
- `POST /api/v1/pos/sales/orders/{id}/payments/`
- `POST /api/v1/pos/sales/payments/{id}/refund/`
- `POST /api/v1/pos/sales/receipts/{id}/reprint/`

### `kitchen`

- `GET /api/v1/pos/kitchen/queue/`
- `GET /api/v1/pos/kitchen/tickets/{id}/`
- `POST /api/v1/pos/kitchen/tickets/{id}/status/`
- `POST /api/v1/pos/kitchen/items/{id}/status/`

## Hozirgi app'lardan yangi app'larga mapping

```text
apps.accounts      -> apps.iam + apps.staffing
apps.admin         -> yo'qoladi, faqat api qatlamlari boshqa app'larga ko'chadi
apps.catalog       -> apps.catalog
apps.dashboard     -> apps.iam + apps.reporting
apps.floor         -> apps.floor
apps.integrations  -> apps.integrations
apps.kitchen       -> apps.kitchen
apps.orders        -> apps.sales
apps.organizations -> apps.platform + apps.restaurants
apps.reports       -> apps.reporting
```

## Tavsiya etilgan migratsiya bosqichlari

### 1-bosqich

- `apps.admin` ichidagi view va serializer'larni yangi app'larga ko'chirish
- URL'larni hozircha alias bilan ushlab turish
- model migratsiyalariga tegmaslik

### 2-bosqich

- `accounts` ichidan `iam` va `staffing` ni ajratish
- `organizations` ichidan `platform` va `restaurants` ni ajratish
- `orders` ni `sales` ga ko'chirish

### 3-bosqich

- frontend'larni canonical URL'ga o'tkazish
- eski `admin/platform/*`, `admin/constructor/*`, `pos/orders/*` yo'llarini deprecated qilish

### 4-bosqich

- `apps.admin` va `apps.dashboard` ni olib tashlash
- eski alias URL'larni tozalash

## Eng muhim nomlash o'zgarishlari

| Hozirgi URL | Tavsiya etilgan URL |
| --- | --- |
| `/api/v1/admin/platform/business-partners/` | `/api/v1/admin/business-partners/` |
| `/api/v1/admin/platform/tariffs/` | `/api/v1/admin/tariffs/` |
| `/api/v1/admin/constructor/restaurants/` | `/api/v1/admin/restaurants/` |
| `/api/v1/admin/constructor/cash-desks/` | `/api/v1/admin/restaurants/current/cash-desks/` |
| `/api/v1/admin/constructor/devices/` | `/api/v1/admin/restaurants/current/devices/` |
| `/api/v1/admin/constructor/prep-stations/` | `/api/v1/admin/restaurants/current/prep-stations/` |
| `/api/v1/admin/constructor/distribution-points/` | `/api/v1/admin/restaurants/current/distribution-points/` |
| `/api/v1/admin/orders/` | `/api/v1/admin/sales/orders/` |
| `/api/v1/admin/payments/` | `/api/v1/admin/sales/payments/` |
| `/api/v1/admin/receipts/` | `/api/v1/admin/sales/receipts/` |
| `/api/v1/pos/orders/` | `/api/v1/pos/sales/orders/` |
| `/api/v1/pos/payments/open-checks/` | `/api/v1/pos/sales/open-checks/` |
| `/api/v1/pos/payments/orders/{id}/pay/` | `/api/v1/pos/sales/orders/{id}/payments/` |
| `/api/v1/pos/receipts/{id}/reprint/` | `/api/v1/pos/sales/receipts/{id}/reprint/` |

## Yakuniy tavsiya

Bu loyiha uchun eng to'g'ri yo'l:

1. backend'ni frontend role-modullariga mos bounded-context'lar bo'yicha bo'lish
2. `apps.admin` ni saqlab qolmaslik
3. canonical URL'larni resource-first qilish
4. `sales`, `restaurants`, `platform`, `iam` ajralishini asosiy refactor sifatida olish

Shu yondashuv bilan backend tuzilmasi `admin-frontend` va `pos-frontend` dagi modul bo'linishi bilan bir xil mental model'ga tushadi.
