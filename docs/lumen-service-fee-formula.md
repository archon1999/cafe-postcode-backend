# Lumen xizmat haqi

Holat: lokal kod va shablon tayyor; production sozlamasiga qo‘llanmagan.
Vaqt zonasi: `Asia/Tashkent`. Parametrlar: `day_rate = 50000`, `night_rate = 100000`.

09:00–18:00 oralig‘ida kirgan mijozning birinchi soati 50 000 so‘m,
18:00–09:00 oralig‘ida kirgan mijozniki 100 000 so‘m. Bir soatdan kam
o‘tirsa ham shu summa olinadi. Birinchi soat ichida tarif almashishi summani
o‘zgartirmaydi. Keyingi vaqt kunduzgi va tungi oraliqlarga bo‘linadi.

```text
let first_hour_rate = if(time_in(session.started_at, "09:00", "18:00"), day_rate, night_rate);
let first_hour_end = add_minutes(session.started_at, 60);
return first_hour_rate + if(duration_minutes <= 60, 0,
  minutes_in(first_hour_end, calculation.at, "09:00", "18:00") / 60 * day_rate
  + minutes_in(first_hour_end, calculation.at, "18:00", "09:00") / 60 * night_rate);
```

| Kirish–chiqish | Xizmat haqi |
| --- | ---: |
| 17:45–18:15 | 50 000 |
| 17:45–18:45 | 50 000 |
| 17:45–19:15 | 100 000 |
| 18:00–18:15 | 100 000 |
| 08:30–09:30 | 100 000 |
| 08:30–10:00 | 125 000 |
| 23:30–ertasi 01:00 | 150 000 |

Birinchi soatdan keyin haqiqiy vaqtga mutanosib hisoblanadi; yakuniy summa butun
so‘mga yaxlitlanadi. Minimum har smenada qaytadan olinmaydi. Formula uchun chekda
faqat `Xizmat haqi: summa` chiqadi.

Formula va `add_minutes` bilan lokal offline POS to‘lovi va qayta sinxronlash
tekshirildi. PostgreSQL migratsiyasi va rollback sinovlari o‘tdi. Production’ga
qo‘llashdan oldin imzolangan yangi Agent/POS tarqatilishi tasdiqlanishi kerak;
eski Agentlarga moslik talab qilinmaydi. Tartib: `service-fee-rollout.md`.
