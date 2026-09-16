from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from legal_monitor.config import load_profiles, load_settings, save_profiles  # noqa: E402
from legal_monitor.monitoring import count_monitoring_shortlist, format_monitoring_period  # noqa: E402
from legal_monitor.pipeline.classify import run_classify  # noqa: E402
from legal_monitor.pipeline.export import ExportFlowResult, run_cleanup, run_export_flow  # noqa: E402
from legal_monitor.pipeline.ingest import run_ingest  # noqa: E402
from legal_monitor.progress import create_progress  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)


def configure_profiles() -> None:
    profiles = load_profiles()
    while True:
        print("\n=== Зоны интереса ===")
        for idx, p in enumerate(profiles, start=1):
            status = "ВКЛ" if p.enabled else "ВЫКЛ"
            print(f"{idx}. [{status}] {p.name} — {p.description}")
            kw = ", ".join(p.rules.keywords_any[:6])
            if len(p.rules.keywords_any) > 6:
                kw += "..."
            print(f"   Ключевые слова: {kw}")
        print("\n0. Сохранить и выйти")
        print("a. Включить/выключить профиль")
        print("b. Добавить ключевое слово")
        print("c. Создать новый профиль")

        choice = input("\nВыбор: ").strip().lower()
        if choice == "0":
            save_profiles(profiles)
            print("Сохранено в config/profiles.yaml")
            break
        if choice == "a":
            num = input("Номер профиля: ").strip()
            if num.isdigit() and 1 <= int(num) <= len(profiles):
                p = profiles[int(num) - 1]
                p.enabled = not p.enabled
                print(f"{'Включён' if p.enabled else 'Выключен'}: {p.name}")
        elif choice == "b":
            num = input("Номер профиля: ").strip()
            word = input("Новое ключевое слово: ").strip().lower()
            if num.isdigit() and 1 <= int(num) <= len(profiles) and word:
                profiles[int(num) - 1].rules.keywords_any.append(word)
                print("Добавлено.")
        elif choice == "c":
            pid = input("ID профиля (латиница, например: pharma): ").strip()
            name = input("Название: ").strip()
            desc = input("Описание: ").strip()
            words = input("Ключевые слова через запятую: ").strip()
            if pid and name:
                from legal_monitor.config import Profile, ProfileRules

                profiles.append(
                    Profile(
                        id=pid,
                        name=name,
                        enabled=True,
                        description=desc,
                        rules=ProfileRules(
                            keywords_any=[w.strip().lower() for w in words.split(",") if w.strip()],
                            keywords_exclude=[],
                        ),
                    )
                )
                print("Профиль создан.")


def show_status(settings) -> None:
    from legal_monitor.models import Document, DocumentProfile, Memo, init_db

    Session = init_db(str(settings.db_path))
    session = Session()
    try:
        docs = session.query(Document).count()
        matches = session.query(DocumentProfile).count()
        memos = session.query(Memo).count()
        shortlist = count_monitoring_shortlist(session, settings)
        enabled = [p.name for p in load_profiles() if p.enabled]
    finally:
        session.close()

    period = format_monitoring_period(settings)
    print("\n=== Статус ===")
    print(f"База данных: {settings.db_path}")
    print(f"Окно мониторинга (дата публикации): {period} ({settings.fetch_window_days} дней)")
    print(f"Хранение: {settings.retention_days} дней")
    print(f"Документов в базе (всего): {docs}")
    print(f"В shortlist (опубликовано + профили): {shortlist['documents']} док., {shortlist['matches']} совпадений")
    print(f"Совпадений с профилями (всего): {matches}")
    print(f"Пояснительных записок: {memos}")
    print(f"Активные профили: {', '.join(enabled) or 'нет'}")


def _print_export_result(result: ExportFlowResult) -> None:
    le = result.list_export
    print(f"\nВыгрузка: Excel: {le.excel}")
    print(f"          Word:  {le.word}")
    print("\n" + "=" * 50)
    print("  ГОТОВО")
    print("  Ниже снова главное меню — введите цифру 0–7.")
    print("=" * 50)


def main() -> None:
    settings = load_settings()

    while True:
        print("\n" + "=" * 50)
        print("  ЮРИДИЧЕСКИЙ МОНИТОРИНГ")
        print("=" * 50)
        print("1. Полный цикл (скачать → классифицировать → выгрузка)")
        print("2. Только скачивание (последние 2 недели, с дедупом)")
        print("3. Только классификация по зонам интереса")
        print("4. Экспорт (список)")
        print("5. Очистка старых данных (пакет 2 недели)")
        print("6. Настроить зоны интереса")
        print("7. Статус")
        print("0. Выход")

        choice = input("\nВыбор: ").strip()

        if choice == "0":
            print("До свидания.")
            break
        elif choice == "1":
            with create_progress() as progress:
                run_ingest(settings, progress=progress)
                run_classify(settings, progress=progress)
                result = run_export_flow(settings, progress=progress)
            _print_export_result(result)
        elif choice == "2":
            with create_progress() as progress:
                stats = run_ingest(settings, progress=progress)
            print(f"\nСкачано: найдено={stats['fetched']}, новых={stats['new']}")
        elif choice == "3":
            with create_progress() as progress:
                stats = run_classify(settings, progress=progress)
            print(f"\nКлассификация: документов={stats['documents']}, совпадений={stats['matches']}")
        elif choice == "4":
            with create_progress() as progress:
                result = run_export_flow(settings, progress=progress)
            _print_export_result(result)
        elif choice == "5":
            stats = run_cleanup(settings)
            print(f"\nУдалено документов: {stats['deleted_docs']}")
        elif choice == "6":
            configure_profiles()
        elif choice == "7":
            show_status(settings)
        else:
            print("Неизвестный пункт меню. Введите цифру от 0 до 7.")


if __name__ == "__main__":
    main()
