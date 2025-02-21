import random
import psycopg2
from telebot import types, TeleBot, custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
import os

from dotenv import load_dotenv
load_dotenv()
db_host = os.getenv('DB_HOST')
db_port = os.getenv('DB_PORT')
db_name = os.getenv('DB_NAME')
db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
API_TOKEN = os.getenv('API_TOKEN')
state_storage = StateMemoryStorage()
bot = TeleBot(API_TOKEN, state_storage=state_storage)


print('Start telegram bot...')
known_users = []
userStep = {}
buttons = []

def init_db():
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )
    return conn

@bot.message_handler(commands=['help'])
def help_command(message):
    cid = message.chat.id
    help_text = (
        """Доступные команды:
        /start или /cards - Запуск бота
        /help - Показать это сообщение
        /clear - Стереть прогресс и добавленные слова"""
    )
    bot.send_message(cid, help_text)
# очистка словарей

@bot.message_handler(commands=['clear'])
def clean_bot(message):
    cid = message.chat.id
    with init_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            TRUNCATE TABLE ignore_words CASCADE;
            TRUNCATE TABLE user_words CASCADE;
            TRUNCATE TABLE words CASCADE;
        """)
        cursor.execute("""
            INSERT INTO words (target_word, translate_word) VALUES 
            ('Bye!', 'Пока!'),
            ('Hi!', 'Привет!'),
            ('to do', 'делать'),
            ('tea', 'чай'),
            ('milk', 'молоко'),
            ('home', 'дом'),
            ('cat', 'кошка'),
            ('flower', 'цветок'),
            ('bus', 'автобус'),
            ('red', 'красный');
        """)

    bot.send_message(cid, "Прогресс очищен, все добавленные слова удалены, для начала нажми /start")

def show_hint(*lines):
    return '\n'.join(lines)

def show_target(data):
    return f"{data['target_word']} -> {data['translate_word']}"

class Command:
    ADD_WORD = 'Добавить слово ➕'
    DELETE_WORD = 'Удалить слово🔙'
    NEXT = 'Дальше ⏭'

class MyStates(StatesGroup):
    target_word = State()
    translate_word = State()
    another_words = State()

def get_user_step(uid):
    if uid in userStep:
        return userStep[uid]
    else:
        known_users.append(uid)
        userStep[uid] = 0
        print("New user detected, who hasn't used \"/start\" yet")
        return 0

# Получает случайное слово из БД
def get_random_word_from_db(message):
    with init_db() as conn:
        cursor = conn.cursor()
        cid = message.chat.id
        cursor.execute("""
                        SELECT w.id, w.target_word, w.translate_word
                        FROM words w
                        LEFT JOIN ignore_words ig ON w.id = ig.word_id AND ig.user_id = %s
                        WHERE ig.word_id IS NULL
                        ORDER BY RANDOM() LIMIT 1;
                    """, (cid,))
        word = cursor.fetchone()
        if word:
            return word
        return None

# Получает список других слов из БД
def get_other_words_from_db():
    with init_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT other_word FROM another_words ORDER BY RANDOM() LIMIT 3;")
        other_words = cursor.fetchall()
        return [word[0] for word in other_words]

@bot.message_handler(commands=['cards', 'start'])
def create_cards(message):
    cid = message.chat.id
    if cid not in known_users:
        known_users.append(cid)
        userStep[cid] = 0
        bot.send_message(cid, """
        Салют! 👋 Давай учить английский! 
        Учеба в удобном для тебя режиме и темпе!
        Собери свой словарь сам!
        Тебе помогут инструменты:
        Добавить слово ➕,
        Удалить слово 🔙.
        Итак, поехали! ⬇️""")

    markup = types.ReplyKeyboardMarkup(row_width=2)
    global buttons
    buttons = []
    result = get_random_word_from_db(message)
    if result:
        word_id, target_word, translate_word = result
        target_word_btn = types.KeyboardButton(target_word)
        buttons.append(target_word_btn)
        # Получаем случайное слово из таблицы another_words
        others = get_other_words_from_db()
        other_words_btns = [types.KeyboardButton(word) for word in others]
        buttons.extend(other_words_btns)
        random.shuffle(buttons)
        next_btn = types.KeyboardButton(Command.NEXT)
        add_word_btn = types.KeyboardButton(Command.ADD_WORD)
        delete_word_btn = types.KeyboardButton(Command.DELETE_WORD)
        buttons.extend([next_btn, add_word_btn, delete_word_btn])
        markup.add(*buttons)
        greeting = f"Выбери перевод слова:\n🇷🇺 {translate_word}"
        bot.send_message(message.chat.id, greeting, reply_markup=markup)
        bot.set_state(message.from_user.id, MyStates.target_word, message.chat.id)
        with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
            data['target_word'] = target_word
            data['translate_word'] = translate_word
            data['other_words'] = others
    else:
        bot.send_message(cid, """ Все слова удалены, добавь новые или начни заново
           при помощи команды /clear """)

@bot.message_handler(func=lambda message: message.text == Command.NEXT)
def next_cards(message):
    create_cards(message)
# Обработчик команды для удаления слова (добавляем в игнор-лист)

@bot.message_handler(func=lambda message: message.text == Command.DELETE_WORD)
def delete_word(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        cid = message.chat.id
        word_to_delete = data['target_word']
        translate_word = data['translate_word']
        word_id = get_word_id(word_to_delete)
        add_to_ignore_words(cid, word_id)
        bot.send_message(cid, f"Слово '{translate_word}' добавлено в игнор-лист")
    create_cards(message)
# Добавляет слово в таблицу ignore_words
def add_to_ignore_words(user_id, word_id):
    with init_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
           INSERT INTO ignore_words (user_id, word_id) 
           VALUES (%s, %s)""", (user_id, word_id))
# Обработчик команды для добавления нового слова
@bot.message_handler(func=lambda message: message.text == Command.ADD_WORD)
def add_word(message):
    cid = message.chat.id
    userStep[cid] = 1
    bot.send_message(message.chat.id, """
       Введите новое слово и его перевод через пробел:
       """)
# Добавляет слова в БД
@bot.message_handler(func=lambda message: get_user_step(message.chat.id) == 1)
def add_word_to_db(message):
    cid = message.chat.id
    with init_db() as conn:
        cursor = conn.cursor()
        target_word, translate_word = message.text.split(' ')
        target_word = target_word.strip()
        translate_word = translate_word.strip()
        cursor.execute("""INSERT INTO words (target_word, translate_word)
           VALUES (%s, %s)
           """, (target_word, translate_word))
        # Подсчитываем количество слов
        cursor.execute("""SELECT COUNT(*) FROM words """)
        word_count = cursor.fetchone()[0]
        bot.send_message(cid, f"Слово '{target_word}' и перевод '{translate_word}' добавлены.\n"
                              f"Теперь в словаре {word_count} слов.")
    userStep[cid] = 0
# Добавление в user_words через обработчик ответа

def insert_user_word(user_id, word_id, passed_word):
    with init_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
               INSERT INTO user_words (user_id, word_id, passed_word) 
               VALUES (%s, %s, %s)
           """, (user_id, word_id, passed_word))

# Получает word_id из таблицы words
def get_word_id(target_word):
    with init_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT id 
           FROM words WHERE target_word = %s""", (target_word,))
        result = cursor.fetchone()
        return result[0] if result else 0

# Обработчик ответа
@bot.message_handler(func=lambda message: True, content_types=['text'])
def message_reply(message):
    text = message.text
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        markup = types.ReplyKeyboardMarkup(row_width=2)
        target_word = data.get('target_word')
        translate_word = data.get('translate_word')
        word_id = get_word_id(target_word)
        passed_word = (text == target_word)
        # Добавляем текущее слово в базу пройденных слов со статусом True/False
        insert_user_word(message.from_user.id, word_id, passed_word)
        if passed_word:
            for btn in buttons:
                if btn.text == text:
                    btn.text = text + '✅'
            hint_text = ["Прекрасно!❤️", show_target(data)]
            hint = show_hint(*hint_text)
        else:
            for btn in buttons:
                if btn.text == text:
                    btn.text = text + '❌'
                    break
            hint = show_hint("Неверно!", f"Пробуй ещё раз! 🇷🇺{translate_word}")
    markup.add(*buttons)
    bot.send_message(message.chat.id, hint, reply_markup=markup)
bot.add_custom_filter(custom_filters.StateFilter(bot))
bot.infinity_polling(skip_pending=True)
