import asyncio
import schedule 
import threading
import time
import pytz
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from schedules import schedules
from config import bot_token

user_data = {}
user_nicknames = {}
user_schedules = {}
user_states = {}  # For handling next step handlers
user_menu = {}  # Tracks where to return keyboard after actions
scheduled_jobs = {}  # Track scheduled jobs for removal
app_instance = None  # Store application instance for scheduled reminders
app_loop = None  # Store application event loop for scheduled reminders

# State constants
STATE_GROUP_CHOICE = 1
STATE_DAY_CHOICE = 2
STATE_REMINDER_TIME = 3

def get_group_by_chat_id(chat_id):
    # Сначала проверяем словарь в памяти
    if chat_id in user_data:
        return user_data[chat_id]
    
    # Если нет в памяти, читаем из файла
    try:
        with open("user_data.txt", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(maxsplit=2)
                if len(parts) >= 2:
                    saved_id_str = parts[0]
                    group = parts[1]
                    nickname = parts[2] if len(parts) >= 3 else ""
                    try:
                        saved_id = int(saved_id_str.strip())
                        if saved_id == chat_id:
                            # Восстанавливаем в памяти для быстрого доступа
                            user_data[chat_id] = group.strip()
                            if nickname:
                                user_nicknames[chat_id] = nickname.strip()
                            return group.strip()
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return None


def load_user_data():
    """Загружает данные пользователей из файла при старте"""
    import os
    global user_data, user_nicknames
    file_path = "user_data.txt"
    
    try:
        if not os.path.exists(file_path):
            print(f"Файл {os.path.abspath(file_path)} не найден, начинаем с пустого списка")
            return
            
        with open(file_path, "r", encoding="utf-8") as f:
            loaded_count = 0
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:  # Пропускаем пустые строки
                    continue
                parts = line.split(maxsplit=2)
                if len(parts) >= 2:
                    try:
                        chat_id = int(parts[0].strip())
                        group = parts[1].strip()
                        nickname = parts[2].strip() if len(parts) >= 3 else ""
                        user_data[chat_id] = group
                        if nickname:
                            user_nicknames[chat_id] = nickname
                        loaded_count += 1
                    except ValueError as e:
                        print(f"Предупреждение: неверный формат в строке {line_num}: {line}")
                        continue
                        
        if loaded_count > 0:
            print(f"✓ Загружено {loaded_count} записей пользователей из {os.path.abspath(file_path)}")
        else:
            print(f"Файл {file_path} существует, но не содержит валидных данных")
            
    except Exception as e:
        print(f"✗ Ошибка при загрузке user_data.txt: {e}")
        import traceback
        traceback.print_exc()


def save_user_data():
    """Сохраняет данные пользователей в файл"""
    import os
    try:
        if not user_data:
            print("Предупреждение: user_data пуст, нечего сохранять")
            return
        
        file_path = "user_data.txt"
        # Создаем резервную копию перед сохранением
        if os.path.exists(file_path):
            backup_path = f"{file_path}.bak"
            try:
                with open(file_path, "r", encoding="utf-8") as src, open(backup_path, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
            except:
                pass
        
        # Сохраняем данные
        with open(file_path, "w", encoding="utf-8") as f:
            for cid, grp in sorted(user_data.items()):  # Сортируем для консистентности
                nick = user_nicknames.get(cid, "").strip()
                if nick:
                    f.write(f"{cid} {grp} {nick}\n")
                else:
                    f.write(f"{cid} {grp}\n")
            f.flush()
            os.fsync(f.fileno())  # Принудительная синхронизация с диском
        
        # Проверяем, что файл был записан
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            print(f"✓ Сохранено {len(user_data)} записей в {os.path.abspath(file_path)}")
        else:
            print(f"✗ ОШИБКА: Файл {file_path} пуст или не создан!")
            
    except Exception as e:
        print(f"✗ Ошибка при сохранении user_data.txt: {e}")
        import traceback
        traceback.print_exc()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # При старте показываем основную клавиатуру без дополнительного сообщения
    await update.message.reply_text(
        "Меню",
        reply_markup=get_main_keyboard()
    )
    user_menu[chat_id] = "main"


def get_main_keyboard():
    keyboard = [
        ['Расписание на сегодня', 'Расписание на завтра'],
        ['Расписание на день недели'],
        ['Настройки'],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_settings_keyboard():
    keyboard = [
        ['Выбрать группу'],
        ['Включить уведомления', 'Выключить уведомления'],
        ['Назад'],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def show_settings(update: Update):
    chat_id = update.effective_chat.id
    user_menu[chat_id] = "settings"
    await update.message.reply_text("Настройки", reply_markup=get_settings_keyboard())


async def show_main(update: Update):
    chat_id = update.effective_chat.id
    user_menu[chat_id] = "main"
    await update.message.reply_text("Меню", reply_markup=get_main_keyboard())


async def process_buttons_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.strip()
    if command == "Выбрать группу":
        await chose_group_command(update, context)
    elif command == "Настройки":
        await show_settings(update)
    elif command == "Назад":
        await show_main(update)
    elif command == "Расписание на день недели":
        await ask_day(update, context)
    elif command == "Расписание на сегодня":
        await send_daily_schedule(update, context, day_offset=0)
    elif command == "Расписание на завтра":
        await send_daily_schedule(update, context, day_offset=1)
    elif command == "Включить уведомления":
        await set_reminder_command(update, context)
    elif command == "Выключить уведомления":
        await remove_reminder_command(update, context)


async def chose_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Получаем все доступные группы из schedules
    available_groups = sorted([str(g) for g in schedules.keys()])
    
    # Размещаем кнопки по 2-3 в строку
    keyboard = []
    for i in range(0, len(available_groups), 3):
        row = available_groups[i:i+3]
        keyboard.append(row)
    
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Какая группа?", reply_markup=reply_markup)
    user_states[chat_id] = STATE_GROUP_CHOICE


async def process_group_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group_str = update.message.text.strip()
    
    # Проверяем, что группа существует в schedules
    try:
        group_num = int(group_str)
        if group_num in schedules:
            user_data[chat_id] = group_str
            # Ник нужен, чтобы можно было понимать, кто именно выбрал группу.
            tg_user = update.effective_user
            nickname = ""
            if tg_user:
                nickname = getattr(tg_user, "username", "") or ""
                if not nickname:
                    nickname = getattr(tg_user, "full_name", "") or ""
                if not nickname:
                    first = getattr(tg_user, "first_name", "") or ""
                    last = getattr(tg_user, "last_name", "") or ""
                    nickname = f"{first} {last}".strip()
            if nickname:
                user_nicknames[chat_id] = nickname
            print(f"Добавлена группа {group_str} для chat_id {chat_id}, всего записей: {len(user_data)}")
            save_user_data()
            keyboard = get_settings_keyboard() if user_menu.get(chat_id) == "settings" else get_main_keyboard()
            await update.message.reply_text(
                f"Выбрана группа {group_str}.",
                reply_markup=keyboard
            )
            user_states.pop(chat_id, None)
            
        else:
            await update.message.reply_text("Неверный выбор. Попробуй снова.")
    except ValueError:
        await update.message.reply_text("Неверный выбор. Попробуй снова.")


def get_schedule(group: int, week: int, day: str) -> str:
    day_schedule = schedules.get(group, {}).get(week, {}).get(day)
    if not day_schedule:
        return "Нет данных"
    if isinstance(day_schedule, str):
        return day_schedule
    if isinstance(day_schedule, dict): 
        # Пустая строка между парами для лучшей читаемости в Telegram
        return "\n\n".join(
            f"{time}: {subject}" for time, subject in sorted(day_schedule.items())
        )
    return str(day_schedule)


async def ask_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keyboard = [['Понедельник', 'Вторник', 'Среда'], ['Четверг', 'Пятница', 'Суббота']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Выбери день", reply_markup=reply_markup)
    user_states[chat_id] = STATE_DAY_CHOICE


async def process_day_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = pytz.timezone("Europe/Minsk")
    now = datetime.now(tz)
    chat_id = update.effective_chat.id
    day = update.message.text.strip()
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
        await update.message.reply_text("Группа не установлена /group")
        return
    week_number = now.isocalendar()[1]
    week = 1 if week_number % 2 == 0 else 2
    schedule_text = get_schedule(int(group), week, day_out)
    await update.message.reply_text(
        f"Расписание за {day} (неделя {week}):\n\n{schedule_text}",
        reply_markup=get_main_keyboard()
    )
    user_states.pop(chat_id, None)
    


async def send_daily_schedule(
    update: Update = None,
    context: ContextTypes.DEFAULT_TYPE = None,
    chat_id: int = None,
    day_offset: int = 0,
):
    if chat_id is None:
        chat_id = update.effective_chat.id
    
    tz = pytz.timezone("Europe/Minsk")
    now = datetime.now(tz) + timedelta(days=day_offset)
    day_name = now.strftime("%A")
    group = get_group_by_chat_id(chat_id)
    if not group:
        if update:
            await update.message.reply_text("Группа не установлена /group")
        else:
            # For scheduled reminders, use the app instance
            if app_instance:
                await app_instance.bot.send_message(chat_id, "Группа не установлена /group")
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
    message_text = f"Расписание за {day_out} (неделя {week}):\n\n{schedule_text}"
    
    if update:
        await update.message.reply_text(message_text, reply_markup=get_main_keyboard())
    else:
        # For scheduled reminders
        if app_instance:
            await app_instance.bot.send_message(chat_id, message_text)


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_daily_schedule(update, context)


async def set_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("Введите время напоминания в 24х часовом формате")
    user_states[chat_id] = STATE_REMINDER_TIME


def send_scheduled_reminder(chat_id: int):
    """Wrapper function for scheduled reminders that runs in async context"""
    if app_instance and app_loop:
        # Schedule coroutine on the main event loop from a separate thread
        future = asyncio.run_coroutine_threadsafe(
            send_daily_schedule(chat_id=chat_id), app_loop
        )
        future.result()  # Wait for completion


async def process_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    global user_schedules, scheduled_jobs

    try:
        reminder_time_str = update.message.text
        reminder_time = datetime.strptime(reminder_time_str, '%H:%M').time()
        # Create a job and store reference
        job = schedule.every().day.at(reminder_time.strftime("%H:%M")).do(
            send_scheduled_reminder, chat_id=chat_id
        )
        scheduled_jobs[chat_id] = job
        user_schedules[chat_id] = reminder_time 
        keyboard = get_settings_keyboard() if user_menu.get(chat_id) == "settings" else get_main_keyboard()
        await update.message.reply_text(
            f"Уведомление поставлено на {reminder_time.strftime('%H:%M')}.",
            reply_markup=keyboard,
        )
        user_states.pop(chat_id, None)
    except ValueError:
        keyboard = get_settings_keyboard() if user_menu.get(chat_id) == "settings" else get_main_keyboard()
        await update.message.reply_text(
            "Попробуй через двоеточие.(/set_reminder)",
            reply_markup=keyboard,
        )


async def remove_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    global scheduled_jobs
    if chat_id in user_schedules:
        # Remove the scheduled job
        if chat_id in scheduled_jobs:
            schedule.cancel_job(scheduled_jobs[chat_id])
            del scheduled_jobs[chat_id]
        del user_schedules[chat_id]
        keyboard = get_settings_keyboard() if user_menu.get(chat_id) == "settings" else get_main_keyboard()
        await update.message.reply_text(
            "Уведомления выключены.",
            reply_markup=keyboard,
        )
    else:
        keyboard = get_settings_keyboard() if user_menu.get(chat_id) == "settings" else get_main_keyboard()
        await update.message.reply_text(
            "Уведомления небыли включены.",
            reply_markup=keyboard,
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = user_states.get(chat_id)
    
    if state == STATE_GROUP_CHOICE:
        await process_group_choice(update, context)
    elif state == STATE_DAY_CHOICE:
        await process_day_choice(update, context)
    elif state == STATE_REMINDER_TIME:
        await process_reminder_time(update, context)
    elif update.message.text in [
        'Выбрать группу',
        'Настройки',
        'Назад',
        'Расписание на день недели',
        'Расписание на сегодня',
        'Расписание на завтра',
        'Включить уведомления',
        'Выключить уведомления'
    ]:
        await process_buttons_commands(update, context)




def run_scheduler():
    """Run scheduler in a separate thread"""
    while True:
        schedule.run_pending()
        delay = schedule.idle_seconds()
        if delay is None:
            time.sleep(1)
        else:
            time.sleep(delay)


def main():
    global app_instance, app_loop
    
    # Загружаем данные пользователей при старте
    load_user_data()
    
    async def initialize_loop(application: Application):
        global app_loop
        app_loop = asyncio.get_running_loop()
    
    application = Application.builder().token(bot_token).post_init(initialize_loop).build()
    app_instance = application  # Store for scheduled reminders
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("group", chose_group_command))
    application.add_handler(CommandHandler("day", ask_day))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("set_reminder", set_reminder_command))
    application.add_handler(CommandHandler("remove_reminder", remove_reminder_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Start bot
    application.run_polling()


if __name__ == '__main__':
    main()
