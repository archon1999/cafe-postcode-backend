# Cafe Postcode ombor v2

## Maqsad

Ombor moduli restoran egasiga uchta savolga dalil bilan javob berishi kerak:

1. Hozir qayerda nima va qancha bor?
2. Xomashyo qayerga va nima sababdan sarflandi?
3. Nazariy sarf, haqiqiy sarf va puldagi farq qancha?

Asosiy oqim:

```text
Yetkazib beruvchi
  -> Xomashyo ombori
  -> Omborlararo transfer
  -> Ishlab chiqarish ombori
  -> Ishlab chiqarish partiyasi
  -> Yarim tayyor mahsulot
  -> Menyu retsepti
  -> POS sotuvi
```

## Mahsulot va narx chegaralari

Tizim bir-biridan farqli qiymatlarni alohida saqlaydi:

- **Xarid narxi** — yetkazib beruvchidan olingan birlik narxi.
- **Xarid chegirmasi** — supplier yoki kirim qatori bo'yicha chegirma; ombor tannarxiga ta'sir qiladi.
- **O'rtacha tannarx** — ledger harakatlaridan hisoblanadi, qo'lda tahrirlanmaydi.
- **Retsept tannarxi** — ingredientlar tannarxi yig'indisi / retsept chiqishi.
- **Sotuv narxi** — katalog mahsulotining POS narxi.
- **Sotuv aksiyasi/chegirmasi** — katalog yoki alohida promotions modulining vazifasi; ombor qoldig'ini o'zgartirmaydi.

Omborda sotuv chegirmasini saqlash tannarx va tushumni aralashtiradi. Ombor supplier narxi va xarid chegirmasini boshqaradi; katalog esa sotuv narxi va aksiyani boshqaradi.

## Domen modeli

### Warehouse

- `kind`: `general | raw | production | sales`
- bitta restoran uchun bitta default consumption ombori
- transfer manbasi va qabul qiluvchi ombori bir xil bo'lmaydi

### InventoryItem

- `kind`: `raw | semi_finished | finished | packaging | non_food`
- asosiy birlik: `g | ml | piece`
- xarid birligi va konversiya koeffitsiyenti
- minimum qoldiq va operatsion farq toleranslari
- `warn | block | off` mavjudlik siyosati

### Recipe

Retseptda aynan bitta natija bo'ladi:

- katalog mahsuloti — POS sotuvda sarflanadigan taom retsepti;
- ombor mahsuloti — ishlab chiqariladigan yarim tayyor mahsulot retsepti.

Retsept qatorlari har qanday ombor mahsulotiga, jumladan boshqa yarim tayyor mahsulotga murojaat qilishi mumkin. Tizim retsept sikllarini (`A -> B -> A`) rad etadi. Har o'zgarish yangi immutable versiya yaratadi.

### Transfer

- source warehouse
- destination warehouse
- mahsulot va miqdor
- source tannarx snapshoti
- draft/post/reversal
- bitta tranzaksiyada source chiqim va destination kirim

Keyingi bosqichda `shipped/received` va yo'ldagi qoldiq qo'shilishi mumkin. Bitta restoran ichidagi MVP uchun atomar transfer yetarli va xatoga chidamli.

### Production batch

- production warehouse
- prep recipe version
- planned output
- actual output
- avtomatik hisoblangan inputlar
- tasdiqlangan waste va sabab
- batch/lot, produced-at, expires-on
- haqiqiy input tannarxi / haqiqiy output orqali yarim tayyor mahsulot tannarxi

Posting bitta tranzaksiyada ingredientlarni chiqaradi va yarim tayyor mahsulotni kirim qiladi. Reversal ikkala tomonni qaytaradi.

## Chicken Burger misoli

1. Xomashyo omboriga tovuq, yog', piyoz va ziravor kirim qilinadi.
2. Kerakli miqdor ishlab chiqarish omboriga transfer qilinadi.
3. `Chicken Patty 120 g` retsepti bo'yicha 100 dona rejalashtiriladi.
4. Oshpaz haqiqiy chiqishni, masalan 98 dona, va chiqindi sababini kiritadi.
5. Posting xomashyoni chiqarib, 98 dona kotletni ishlab chiqarish omboriga qo'shadi.
6. `CHICKEN BURGER` katalog retsepti `Chicken Patty 120 g x 1` va boshqa ingredientlarni sarflaydi.
7. POS mavjudlikni yarim tayyor kotlet va qolgan ingredientlar bo'yicha tekshiradi.

## Actual vs Theoretical

```text
Haqiqiy sarf = boshlang'ich qoldiq + kirim + inbound transfer
                + production output - outbound transfer - yakuniy qoldiq

Nazariy sarf = sotilgan taomlar x immutable retsept snapshotlari

Izohlanmagan farq = haqiqiy sarf - nazariy sarf
                    - tasdiqlangan waste - boshqa izohlangan tuzatishlar
```

Yarim tayyor mahsulot ikki marta hisoblanmaydi. Ishlab chiqarish omborida prep alohida SKU sifatida kuzatiladi; xomashyo darajasidagi AvT hisobotida prep ishlab chiqarish retseptiga yoyiladi.

## UX tuzilmasi

Sidebar ichida ombor submenu bo'lib qoladi:

- Dashboard/Qoldiqlar
- Hujjatlar
- Transferlar
- Ishlab chiqarish
- Inventarizatsiya
- Mahsulotlar
- Yetkazib beruvchilar va narxlar
- Hisobotlar
- AI tavsiyalar
- Omborlar va sozlamalar

Katalog mahsuloti tahrirlash sahifasi:

- **Asosiy** tab — nom, kategoriya, MXIK, rasm, sotuv narxi, modifierlar.
- **Retsept** tab — output, yield, trigger, ingredientlar, modifier shartlari, tannarx va marja.

Yangi katalog mahsuloti avval saqlanadi; shundan so'ng Retsept tabi ochiladi. Bu orphan retsept va murakkab ikki endpointli rollbackni oldini oladi.

Ro'yxat sahifalarida bir xil naqsh qo'llanadi: asosiy action o'ngda, qidiruv va filtrlash bitta qatorda, KPI kartalar faqat qaror qabul qilishga yordam berganda, table row orqali detail drawer/dialog, user tanlaydigan ustunlar va saqlanadigan filterlar.

## GPT va MCP

Mavjud ikki yo'l saqlanadi:

1. Admin UI ichidagi user-triggered AI tahlil — server Responses API orqali, structured output va evidence ID bilan.
2. ChatGPT MCP — OAuth, tenant scope va read-only report tools orqali foydalanuvchi ChatGPT ichida savol beradi.

MCP uchun qo'shiladigan read-only vositalar:

- `get_inventory_summary`
- `get_inventory_variance`
- `get_production_yield`
- `get_recipe_costs`
- `get_purchase_recommendations`

GPT hech qachon ledger, retsept, narx yoki hujjatni o'zi o'zgartirmaydi. Keyingi write-actionlar faqat foydalanuvchi ko'rib tasdiqlaydigan draft yaratish bilan cheklanadi.

## Yetkazib berish bosqichlari

### P0 — hisobning yaxlitligi

- warehouse/item kind
- katalogdagi alohida Recipe tab
- prep recipe va cycle validation
- transfer hujjati
- production batch
- posting/reversal va tenant/permission testlari

### P1 — operatsion nazorat

- supplier price va receipt discount snapshoti
- lot qoldig'i, expiry va FEFO
- waste reason katalogi
- production planned/actual yield
- kengaytirilgan AvT

### P2 — qaror va avtomatizatsiya

- MCP inventory reports
- demand/production/purchase forecast
- supplier price anomaly
- evidence-grounded GPT recommendations
- draft purchase/production proposal, inson tasdig'i bilan

## Qabul mezonlari

- Transfer source qoldig'ini kamaytirib destination qoldig'ini aynan shu qiymatda oshiradi.
- Posting qisman muvaffaqiyatli bo'lmaydi; xato bo'lsa barcha harakat rollback qilinadi.
- Production xomashyo va outputni bir tranzaksiyada yozadi.
- Reversal original tarixni o'zgartirmaydi va qarama-qarshi harakat yaratadi.
- Prep recipe sikllari rad etiladi.
- Eski sotuv eski retsept snapshotini saqlaydi.
- Katalog Recipe tabi shu mahsulotning aktiv retseptini ko'rsatadi va yangi versiya yaratadi.
- Sales discount ombor tannarxini o'zgartirmaydi; receipt discount esa net xarid tannarxiga kiradi.
- AI tavsiyasi aniq evidence ID va hisob oralig'ini ko'rsatadi; write action bajarmaydi.
