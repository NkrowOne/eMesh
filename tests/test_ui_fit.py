"""Keyboards never show a label cut on a phone: a row that doesn't fit is split and a grid uses fewer columns."""
from __future__ import annotations

from app.ui.callbacks import MenuCB
from app.ui.common import btn, grid, kb, label_width


def _rows(*labels_by_row: list[str]) -> list[list[str]]:
    markup = kb(*[[btn(label, MenuCB(screen="home")) for label in row] for row in labels_by_row])
    return [[b.text for b in row] for row in markup.inline_keyboard]


def test_label_width_counts_emoji_double() -> None:
    assert label_width("📊 Estadísticas") == 15 and label_width("⚙️ Ajustes") == 10


def test_short_pairs_stay_together_and_long_ones_get_a_row_each() -> None:
    assert _rows(["📝 Mensajes", "⏰ Horarios"]) == [["📝 Mensajes", "⏰ Horarios"]]
    assert _rows(["📣 Canales y grupos", "🗂 Grupos de canales"]) == [["📣 Canales y grupos"], ["🗂 Grupos de canales"]]
    assert _rows(["🗑 Quitar de la red", "🚫 Bloquear"]) == [["🗑 Quitar de la red"], ["🚫 Bloquear"]]


def test_three_in_a_row_fall_back_to_pairs() -> None:
    assert _rows(["⚪ Abierta", "⚪ Con permiso", "⚪ Cerrada"]) == [["⚪ Abierta", "⚪ Con permiso"], ["⚪ Cerrada"]]


def test_list_rows_and_small_buttons_are_left_alone() -> None:
    assert _rows(["#1 📣 Canal de cine y series", "✅", "❌"]) == [["#1 📣 Canal de cine y series", "✅", "❌"]]
    assert len(_rows(["1", "2", "3", "4", "5", "6"])[0]) == 6


def test_grid_uses_fewer_columns_when_a_label_is_long() -> None:
    def make(labels: list[str]) -> list[list[str]]:
        return [[b.text for b in row] for row in grid([btn(x, MenuCB(screen="home")) for x in labels], 3)]

    assert make(["⚪ 2 al día", "⚪ 4 al día", "⚪ 6 al día"]) == [["⚪ 2 al día", "⚪ 4 al día", "⚪ 6 al día"]]
    assert make(["✅ Sin límite", "⚪ 2 al día", "⚪ 4 al día"]) == [["✅ Sin límite", "⚪ 2 al día"], ["⚪ 4 al día"]]
