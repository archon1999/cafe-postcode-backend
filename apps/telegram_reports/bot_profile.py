BOT_NAME = "PosCode Hisobot"
BOT_DESCRIPTION = (
    "Shahobchalaringiz tushumi, buyurtmalar soni, o‘rtacha chek va top mahsulotlarini kuzating. "
    "Kunlik, haftalik va oylik hisobotlar avtomatik yuboriladi."
)
BOT_SHORT_DESCRIPTION = "Shahobchalaringiz uchun qulay kunlik, haftalik va oylik savdo hisobotlari."

BOT_COMMANDS = [
    {"command": "start", "description": "Botni ishga tushirish"},
    {"command": "connect", "description": "Shahobcha kodlarini ulash"},
    {"command": "disconnect", "description": "Shahobchani uzish"},
    {"command": "notifications_on", "description": "Avtomatik hisobotlarni yoqish"},
    {"command": "notifications_off", "description": "Avtomatik hisobotlarni o‘chirish"},
    {"command": "today", "description": "Bugungi hisobotni olish"},
    {"command": "settings", "description": "Joriy sozlamalarni ko‘rish"},
    {"command": "help", "description": "Yordam va komandalar"},
]

