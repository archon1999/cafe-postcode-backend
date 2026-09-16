# Qamish ombori: qisqa qo‘llanma

## Ishlash oqimi

1. **Ma’lumotnomalar** — avval omborlar, mahsulotlar va yetkazib beruvchilar kiritiladi. Qamishda uchta ombor ishlatiladi: `Xomashyo`, `Ishlab chiqarish`, `Sotuv`.
2. **Kirim** — faktura bo‘yicha xomashyo `Xomashyo ombori`ga qabul qilinadi. Chegirmagacha narx, chegirma, partiya va yaroqlilik sanasi shu hujjatda yoziladi.
3. **Ishlab chiqarishga transfer** — kotlet yoki fri tayyorlash uchun kerakli mahsulotlar `Xomashyo`dan `Ishlab chiqarish` omboriga o‘tkaziladi.
4. **Ishlab chiqarish** — texnologik karta rejalashtirilgan xomashyoni chiqaradi va haqiqiy tayyor mahsulotni kirim qiladi. Reja va haqiqiy chiqish farqi alohida ko‘rinadi.
5. **Sotuv omboriga transfer** — yarim tayyor mahsulotlar, sabzavot, qadoq va ichimliklar `Sotuv ombori`ga o‘tkaziladi.
6. **Katalog retsepti** — menyudagi taom ingredientlarga bog‘lanadi. POS oshxonaga yuborganda sarf yoziladi. `Piyozsiz` kabi xususiyat ingredientni sarfdan olib tashlaydi, qo‘shimcha pishloq yoki kotlet esa sarfni oshiradi.
7. **Chiqim** — buzilish, yaroqsiz mahsulot, xodim ovqati yoki boshqa asoslangan sarf alohida chiqim hujjati bilan yoziladi.
8. **Inventarizatsiya** — fizik sanash kiritiladi. Tizim hisobiy va haqiqiy qoldiq farqini miqdor hamda qiymatda ko‘rsatadi.
9. **Nazorat** — qoldiq, kirim-chiqim, tannarx, ishlab chiqarish chiqishi, kamomad, muddati yaqin partiyalar va AI tavsiyalari kuzatiladi.

## Kundalik tartib

- Omborchi har bir kirimni faktura bilan kiritadi va tasdiqlaydi.
- Oshxona mas’uli ishlab chiqarish partiyasida reja va haqiqiy chiqishni yozadi.
- Transfer qabul qiluvchi omborga yetib borgach tasdiqlanadi.
- POS retsept sarfini avtomatik yozadi; qo‘lda takroriy chiqim kiritilmaydi.
- Smena oxirida chiqindi va buzilish dalolatnomasi kiritiladi.
- Tez buziladigan mahsulotlar har kuni, qolganlari haftalik sanaladi.
- 5% atrofidagi kichik og‘ish kuzatiladi; chegaradan oshgan yoki takrorlangan farq tekshiriladi.

## Seeder yaratadigan holat

`seed_qamish_inventory` faqat Qamish UUID va aniq nomi mos kelganda ishlaydi. Katalog, xususiyatlar, buyurtmalar va moliyaviy sotuv tarixiga tegmaydi; faqat shu restoranning ombor yozuvlarini almashtiradi.

Seeder quyidagilarni yaratadi:

- 3 ombor, 4 yetkazib beruvchi va 26 ombor mahsuloti;
- real narx, chegirma, partiya va yaroqlilik sanali 7 kirim;
- xomashyo va tayyor mahsulotlar uchun 3 transfer;
- Chicken Patty, mol go‘shti kotleti va fri kartoshkasi uchun 3 ishlab chiqarish partiyasi;
- 5 katalog retsepti va burger xususiyatlarining sarf qoidalari;
- 12 kunlik jamlangan POS retsept sarfi;
- buzilish chiqimi va ikki nazorat inventarizatsiyasi;
- narx oshishi, ishlab chiqarish og‘ishi, takroriy kamomad, muddati yaqin partiya va nol qoldiqni ko‘rsatadigan tahlil holatlari.

Production buyrug‘i:

```bash
python manage.py seed_qamish_inventory \
  --restaurant-id bf4e5bb4-fc17-486a-b332-f67fc75af5f0 \
  --confirm-name '"Qamish Gamburg"' \
  --reference-date YYYY-MM-DD \
  --apply
```

Command tranzaksiya ichida ishlaydi: biror qator yaratilmasa, tozalash ham rollback bo‘ladi.
