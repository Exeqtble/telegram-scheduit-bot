import telebot
import threading
import schedule
import time
import pytz
from datetime import datetime
from telebot import TeleBot, types
from schedules import schedules

user_data = {}
BOT_TOKEN = 'Bot_token'
bot = telebot.TeleBot(BOT_TOKEN)
user_schedules = {}

@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Введите сначала группу.", )
    buttons(message)

def buttons(message):
    chat_id = message.chat.id
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(
        'Выбрать группу',
        'Расписание на день недели',
        'Расписание на сегодня',
        'Включить уведомления',
        'Выключить уведомления'
    )
   
    bot.send_message(chat_id, "Выбери действие:", reply_markup=keyboard)

    bot.register_next_step_handler(message, process_buttons_commands)


@bot.message_handler(func=lambda m: m.text in [
    'Выбрать группу',
    'Расписание на день недели',
    'Расписание на сегодня',
    'Включить уведомления',
    'Выключить уведомления'
])
def process_buttons_commands(message):
    chat_id = message.chat.id
    command = message.text.strip()
    if command == "Выбрать группу":
       chose_group_command(message)
    elif command == "Расписание на день недели":
       ask_day(message)
    elif command == "Расписание на сегодня":
        send_daily_schedule(message)
    elif command == "Включить уведомления":
        set_reminder_command(message)
    elif command == "Выключить уведомления":
        remove_reminder_command(message)

@bot.message_handler(commands=['group'])
def chose_group_command(message):
    chat_id = message.chat.id
    keyboard = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    keyboard.add('1', '2')
    bot.send_message(chat_id, "Какая группа?", reply_markup=keyboard)
    bot.register_next_step_handler(message, process_group_choice)

def process_group_choice(message):
    chat_id = message.chat.id
    group = message.text.strip()
    if group in ['1']:
        bot.send_message(chat_id, "Выбрана 1 группа.")
    elif group in['2']:
        bot.send_message(chat_id, "Выбрана 2 группа.")
    else:
        bot.send_message(chat_id, "Неверный выбор. Попробуй снова.")
        return
    user_data[chat_id] = group
    print(f"Сюдаа {chat_id}: {group}")
    with open("user_data.txt", "w", encoding="utf-8") as f:
     for cid, grp in user_data.items():
        print(cid, grp, file=f)
     buttons(message)


def get_group_by_chat_id(chat_id):
    with open("user_data.txt", "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                saved_id, group = parts
                if saved_id.strip() == str(chat_id).strip():
                    return group.strip()

    return None




def get_schedule(group: int, week: int, day: str) -> str:
    day_schedule = schedules.get(group, {}).get(week, {}).get(day)
    if not day_schedule:
        return "Нет данных"
    if isinstance(day_schedule, str):
        return day_schedule
    if isinstance(day_schedule, dict): 
        return "\n".join(f"{time}: {subject}" for time, subject in sorted(day_schedule.items()))
    return str(day_schedule)


@bot.message_handler(commands=['day'])
def ask_day(message):
    chat_id = message.chat.id
    keyboard = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    keyboard.add('Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота💀')
    bot.send_message(chat_id, "Выбери день", reply_markup=keyboard)
    bot.register_next_step_handler(message, process_day_choice)

def process_day_choice(message):
    tz = pytz.timezone("Europe/Minsk")
    now = datetime.now(tz)
    chat_id = message.chat.id
    day = message.text.strip()
    group = get_group_by_chat_id(chat_id)
    ru_to_en = {
        "понедельник": "Monday",
        "вторник": "Tuesday",
        "среда": "Wednesday",
        "четверг": "Thursday",
        "пятница": "Friday",
        "суббота": "Saturday",
        "воскресенье": "Sunday"
    }
    day_clean = day.strip().lower()
    day_out = ru_to_en.get(day_clean, day)
    if not group:
        bot.send_message(chat_id, "Группа не установлена /group")
        return
    week_number = now.isocalendar()[1]
    week = 1 if week_number % 2 == 0 else 2
    schedule_text = get_schedule(int(group), week, day_out)
    bot.send_message(chat_id, f"Расписание за {day} (неделя {week}):\n{schedule_text}")
    buttons(message)

def send_daily_schedule(message):
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    day_name = now.strftime("%A")
    chat_id = message.chat.id
    group = get_group_by_chat_id(chat_id)
    if not group:
        bot.send_message(chat_id, "Группа не установлена /group")
        return
    week_number = now.isocalendar()[1]
    week = 1 if week_number % 2 == 0 else 2
    schedule_text = get_schedule(int(group), week, day_name)
    en_ru = {
       "monday": "Понедельник",
       "tuesday": "Вторник",
       "wednesday": "Среда",
       "thursday": "Четверг",
       "friday": "Пятница",
       "saturday": "Суббота",
       "sunday": "Воскресенье"
    }
    day_clean = day_name.strip().lower()
    day_out = en_ru.get(day_clean, day_name)
    bot.send_message(chat_id, f"Расписание за {day_out} (неделя {week}):\n{schedule_text}")
    buttons(message)

@bot.message_handler(commands=['schedule'])
def schedule_command(message):
    chat_id = message.chat.id
    send_daily_schedule(chat_id)

@bot.message_handler(commands=['set_reminder'])
def set_reminder_command(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Введите время напоминания в 24х часовом формате")
    bot.register_next_step_handler(message, process_reminder_time)

def process_reminder_time(message):
    chat_id = message.chat.id
    global user_schedules


    try:
        reminder_time_str = message.text
        reminder_time = datetime.strptime(reminder_time_str, '%H:%M').time()
        schedule.every().day.at(reminder_time.strftime("%H:%M")).do(send_daily_schedule, chat_id=chat_id)
        user_schedules[chat_id] = reminder_time 
        bot.send_message(chat_id, f"Уведомление поставлено на {reminder_time.strftime('%H:%M')}.")
    except ValueError:
        bot.send_message(chat_id, "Попробуй через двоеточие.(/set_reminder)")

@bot.message_handler(commands=['remove_reminder'])
def remove_reminder_command(message):
    chat_id = message.chat.id
    if chat_id in user_schedules:
        schedule.clear(chat_id)
        del user_schedules[chat_id]
        bot.send_message(chat_id, "Уведомления выключены.")
    else:
        bot.send_message(chat_id, "Уведомления небыли включены.")

def bot_polling():
    bot.polling(none_stop=True)

threading.Thread(target=bot_polling).start()

while True:
    schedule.run_pending()
    time.sleep(1)
