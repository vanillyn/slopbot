from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from typing import Any, ClassVar

import discord
from discord import ui

ButtonCallback = Callable[
    ["BaseButton", discord.Interaction],
    Coroutine[Any, Any, None],
]

ConfirmCallback = Callable[
    [discord.Interaction, bool],
    Coroutine[Any, Any, None],
]

PageBuilder = Callable[["PaginatedLayout"], None]


class BaseButton(ui.Button["BaseView"]):
    def __init__(
        self,
        *,
        label: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        custom_id: str | None = None,
        disabled: bool = False,
        row: int | None = None,
    ) -> None:
        super().__init__(
            label=label,
            style=style,
            custom_id=custom_id,
            disabled=disabled,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        raise NotImplementedError


class BaseView(ui.View):
    def __init__(self, *, timeout: float | None = 180.0) -> None:
        super().__init__(timeout=timeout)

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True  # type: ignore[union-attr]


class ConfirmView(BaseView):
    def __init__(
        self,
        callback: ConfirmCallback,
        *,
        confirm_label: str = "confirm",
        cancel_label: str = "cancel",
        timeout: float | None = 30.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._cb = callback
        self.add_item(_ConfirmButton(label=confirm_label, confirmed=True))
        self.add_item(_ConfirmButton(label=cancel_label, confirmed=False))

    async def _invoke(self, interaction: discord.Interaction, confirmed: bool) -> None:
        self.stop()
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True  # type: ignore[union-attr]
        await self._cb(interaction, confirmed)


class _ConfirmButton(ui.Button["ConfirmView"]):
    def __init__(self, *, label: str, confirmed: bool) -> None:
        style = discord.ButtonStyle.success if confirmed else discord.ButtonStyle.danger
        super().__init__(label=label, style=style)
        self._confirmed = confirmed

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await self.view._invoke(interaction, self._confirmed)


class PersistentButton(ui.DynamicItem[ui.Button[ui.View]], template=r""):
    TEMPLATE: ClassVar[re.Pattern[str]]

    def __init_subclass__(cls, *, template: str) -> None:
        super().__init_subclass__(template=template)
        cls.TEMPLATE = re.compile(template)

    def __init__(
        self,
        item: ui.Button[ui.View],
        *,
        row: int | None = None,
    ) -> None:
        super().__init__(item, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        raise NotImplementedError


class RoleButton(BaseView):
    def __init__(
        self,
        role_map: dict[str, int],
        *,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        for label, role_id in role_map.items():
            self.add_item(_RoleButton(label=label, role_id=role_id, style=style))


class _RoleButton(ui.Button["RoleButton"]):
    def __init__(
        self,
        *,
        label: str,
        role_id: int,
        style: discord.ButtonStyle,
    ) -> None:
        super().__init__(label=label, style=style, custom_id=f"rrole:{role_id}")
        self._role_id = role_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            return
        role = interaction.guild.get_role(self._role_id)
        if role is None:
            await interaction.response.send_message("role not found", ephemeral=True)
            return
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(
                f"removed **{role.name}**", ephemeral=True
            )
        else:
            await member.add_roles(role)
            await interaction.response.send_message(
                f"added **{role.name}**", ephemeral=True
            )


class BaseModal(ui.Modal):
    def __init__(
        self,
        *,
        title: str,
        custom_id: str,
        timeout: float | None = None,
    ) -> None:
        super().__init__(title=title, custom_id=custom_id, timeout=timeout)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raise NotImplementedError

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        await interaction.response.send_message("something went wrong", ephemeral=True)
        raise error


class InputField(ui.TextInput["BaseModal"]):
    def __init__(
        self,
        *,
        label: str,
        custom_id: str,
        placeholder: str | None = None,
        required: bool = True,
        style: discord.TextStyle = discord.TextStyle.short,
        min_length: int | None = None,
        max_length: int | None = None,
        default: str | None = None,
    ) -> None:
        super().__init__(
            label=label,
            custom_id=custom_id,
            placeholder=placeholder,
            required=required,
            style=style,
            min_length=min_length,
            max_length=max_length,
            default=default,
        )


class BaseContainer(ui.Container["BaseLayout"]):
    def __init__(
        self,
        *children: ui.Item["BaseLayout"],
        accent_color: int | None = None,
    ) -> None:
        super().__init__(*children, accent_color=accent_color)

    def add_text(self, content: str) -> "BaseContainer":
        self.add_item(ui.TextDisplay(content))
        return self

    def add_sep(self, *, large: bool = False) -> "BaseContainer":
        spacing = (
            discord.SeparatorSpacing.large if large else discord.SeparatorSpacing.small
        )
        self.add_item(ui.Separator(spacing=spacing))
        return self


class BaseLayout(ui.LayoutView):
    def __init__(self, *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)

    def add_text(self, content: str) -> "BaseLayout":
        self.add_item(ui.TextDisplay(content))
        return self

    def add_sep(self, *, large: bool = False) -> "BaseLayout":
        spacing = (
            discord.SeparatorSpacing.large if large else discord.SeparatorSpacing.small
        )
        self.add_item(ui.Separator(spacing=spacing))
        return self

    def add_container(
        self,
        *children: ui.Item["BaseLayout"],
        accent_color: int | None = None,
    ) -> "BaseLayout":
        self.add_item(BaseContainer(*children, accent_color=accent_color))
        return self

    def add_section(
        self,
        text: str,
        accessory: "ui.Button[BaseLayout] | ui.Thumbnail",
    ) -> "BaseLayout":
        self.add_item(ui.Section(ui.TextDisplay(text), accessory=accessory))
        return self

    def add_gallery(self, *items: discord.MediaGalleryItem) -> "BaseLayout":
        self.add_item(ui.MediaGallery(*items))
        return self


class PaginatedLayout(BaseLayout):
    def __init__(
        self,
        pages: list[PageBuilder],
        *,
        index: int = 0,
        timeout: float | None = 120.0,
        prev_label: str = "prev",
        next_label: str = "next",
        show_counter: bool = True,
    ) -> None:
        super().__init__(timeout=timeout)
        self._pages = pages
        self._index = index
        self._prev_label = prev_label
        self._next_label = next_label
        self._show_counter = show_counter
        self._render()

    def _render(self) -> None:
        self._pages[self._index](self)
        self.add_sep()
        self._add_nav()

    def _add_nav(self) -> None:
        total = len(self._pages)
        nav_opts = dict(
            pages=self._pages,
            prev_label=self._prev_label,
            next_label=self._next_label,
            show_counter=self._show_counter,
            timeout=self.timeout,
        )
        row: ui.ActionRow["PaginatedLayout"] = ui.ActionRow()
        row.add_item(
            _NavButton(
                label=self._prev_label,
                target=self._index - 1,
                disabled=self._index == 0,
                custom_id="page:prev",
                **nav_opts,  # pyright: ignore[reportArgumentType]
            )
        )
        if self._show_counter:
            row.add_item(
                ui.Button(
                    label=f"{self._index + 1} / {total}",
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                    custom_id="page:counter",
                )
            )
        row.add_item(
            _NavButton(
                label=self._next_label,
                target=self._index + 1,
                disabled=self._index == total - 1,
                custom_id="page:next",
                **nav_opts,  # pyright: ignore[reportArgumentType]
            )
        )
        self.add_item(row)


class _NavButton(ui.Button["PaginatedLayout"]):
    def __init__(
        self,
        *,
        label: str,
        pages: list[PageBuilder],
        target: int,
        disabled: bool,
        prev_label: str,
        next_label: str,
        show_counter: bool,
        timeout: float | None,
        custom_id: str,
    ) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
            custom_id=custom_id,
        )
        self._pages = pages
        self._target = target
        self._prev_label = prev_label
        self._next_label = next_label
        self._show_counter = show_counter
        self._timeout = timeout

    async def callback(self, interaction: discord.Interaction) -> None:
        new_layout = PaginatedLayout(
            self._pages,
            index=self._target,
            timeout=self._timeout,
            prev_label=self._prev_label,
            next_label=self._next_label,
            show_counter=self._show_counter,
        )
        await interaction.response.edit_message(view=new_layout)


def text_layout(
    content: str,
    *,
    accent_color: int | None = None,
    timeout: float | None = None,
) -> BaseLayout:
    layout = BaseLayout(timeout=timeout)
    layout.add_container(ui.TextDisplay(content), accent_color=accent_color)
    return layout


def paginate(
    pages: list[PageBuilder],
    *,
    index: int = 0,
    timeout: float | None = 120.0,
    prev_label: str = "prev",
    next_label: str = "next",
    show_counter: bool = True,
) -> PaginatedLayout:
    return PaginatedLayout(
        pages,
        index=index,
        timeout=timeout,
        prev_label=prev_label,
        next_label=next_label,
        show_counter=show_counter,
    )


def confirm(
    callback: ConfirmCallback,
    *,
    confirm_label: str = "confirm",
    cancel_label: str = "cancel",
    timeout: float | None = 30.0,
) -> ConfirmView:
    return ConfirmView(
        callback,
        confirm_label=confirm_label,
        cancel_label=cancel_label,
        timeout=timeout,
    )


def reaction_roles(
    role_map: dict[str, int],
    *,
    style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    timeout: float | None = None,
) -> RoleButton:
    return RoleButton(role_map, style=style, timeout=timeout)
