from __future__ import annotations
import flet as ft
VIEWS=['Dashboard','Incoming / Scan','Staging Review','Book Detail','Jobs','Failed','Ready for Library','Converted Source Archive','Settings']
def main(page: ft.Page):
    page.title='ABS Librarian'; page.theme_mode=ft.ThemeMode.DARK; page.scroll=ft.ScrollMode.AUTO
    page.add(ft.Text('ABS Librarian', size=28, weight=ft.FontWeight.BOLD), ft.Text('Audiobookshelf conversion workflow dashboard'), ft.ResponsiveRow([ft.Container(ft.Text(v), col={'sm':12,'md':4,'xl':3}, padding=10, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=8) for v in VIEWS]))
if __name__ == '__main__': ft.app(target=main, view=ft.AppView.WEB_BROWSER)
