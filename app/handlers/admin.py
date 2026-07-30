"""Interactive Telegram Admin Panel."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.config import settings
from app.database import get_session
from app.models import Document, User
from app.services import document as doc_service
from app.services import user as user_service
from app.utils.logger import logger
from app.utils.validators import sanitise_text

router = Router()


class AdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user and message.from_user.id in settings.admin_ids_list

router.message.filter(AdminFilter())
router.callback_query.filter(F.data.startswith("adm:"))


def admin_menu_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Statistics", callback_data="adm:stats")
    kb.button(text="👥 Users", callback_data="adm:users:1")
    kb.button(text="📄 Documents", callback_data="adm:docs:1")
    kb.button(text="⏳ Pending", callback_data="adm:pend:1")
    kb.adjust(2)
    return kb.as_markup()

def admin_stats_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Back to Menu", callback_data="adm:menu")
    return kb.as_markup()

def admin_users_kb(users: list[User], page: int, total_pages: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    for u in users:
        prem = "⭐" if u.is_premium else "🆓"
        kb.button(text=f"{prem} {u.first_name or 'User'} (@{u.username or 'NA'})", callback_data=f"adm:u:{u.telegram_id}")
    kb.adjust(1)
    nav = []
    if page > 1: nav.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"adm:users:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"adm:users:{page + 1}"))
    if len(nav) > 1: kb.row(*nav)
    kb.button(text="🔙 Back to Menu", callback_data="adm:menu")
    return kb.as_markup()

def admin_user_actions_kb(telegram_id: int, is_premium: bool):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    if is_premium: kb.button(text="❌ Revoke Premium", callback_data=f"adm:u:{telegram_id}:revoke")
    else: kb.button(text="⭐ Grant Premium (30d)", callback_data=f"adm:u:{telegram_id}:grant")
    kb.button(text="🔄 Reset Search Count", callback_data=f"adm:u:{telegram_id}:reset")
    kb.button(text="🔙 Back to Users", callback_data="adm:users:1")
    kb.adjust(1)
    return kb.as_markup()

def admin_docs_kb(docs: list[Document], page: int, total_pages: int, prefix: str):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    for d in docs:
        status = "⏳" if not d.approved else "✅"
        kb.button(text=f"{status} {d.file_name[:40]}...", callback_data=f"adm:doc:{d.id}")
    kb.adjust(1)
    nav = []
    if page > 1: nav.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"{prefix}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"{prefix}:{page + 1}"))
    if len(nav) > 1: kb.row(*nav)
    kb.button(text="🔙 Back to Menu", callback_data="adm:menu")
    return kb.as_markup()

def admin_doc_actions_kb(doc_id: int, approved: bool):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    if not approved: kb.button(text="✅ Approve", callback_data=f"adm:doc:{doc_id}:approve")
    kb.button(text="🗑 Delete", callback_data=f"adm:doc:{doc_id}:delete")
    kb.button(text="🔙 Back to List", callback_data="adm:docs:1")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔧 <b>Admin Panel</b>\n\nWelcome to the control center. Select an option below:", reply_markup=admin_menu_kb())

@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🔧 <b>Admin Panel</b>\n\nSelect an option below:", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "adm:stats")
async def cb_admin_stats(callback: CallbackQuery):
    async with get_session() as session:
        stats = await user_service.get_stats(session)
    text = (
        "📊 <b>ExamHub Statistics</b>\n\n"
        f"📄 Total Documents: <b>{stats['total_documents']}</b>\n"
        f"👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"⭐ Premium Users: <b>{stats['premium_users']}</b>\n"
        f"🔍 Searches Today: <b>{stats['searches_today']}</b>\n"
        f"📤 Uploads Today: <b>{stats['uploads_today']}</b>\n"
        f"⏳ Pending Documents: <b>{stats['pending_documents']}</b>"
    )
    await callback.message.edit_text(text, reply_markup=admin_stats_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("adm:users:"))
async def cb_admin_users(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    per_page = 5
    async with get_session() as session:
        total = (await session.execute(select(func.count(User.id)))).scalar() or 0
        result = await session.execute(select(User).order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page))
        users = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)
    await callback.message.edit_text(f"👥 <b>Users Management</b> ({total} total)\nSelect a user:", reply_markup=admin_users_kb(users, page, total_pages))
    await callback.answer()

@router.callback_query(F.data.startswith("adm:u:"))
async def cb_admin_user_actions(callback: CallbackQuery):
    parts = callback.data.split(":")
    telegram_id = int(parts[2])
    if len(parts) == 3:
        async with get_session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
        if not user:
            await callback.answer("User not found.", show_alert=True)
            return
        prem_status = "⭐ ACTIVE" if user.is_premium else "❌ INACTIVE"
        if user.premium_expiry: prem_status += f" (until {user.premium_expiry.strftime('%Y-%m-%d')})"
        text = (
            f"👤 <b>User Profile</b>\n\n"
            f"🆔 ID: <code>{user.telegram_id}</code>\n"
            f"👤 Name: {user.first_name or 'N/A'}\n"
            f" USERNAME: @{user.username or 'N/A'}\n\n"
            f"📊 Search Count: {user.search_count}\n"
            f"📤 Upload Count: {user.upload_count}\n"
            f"🎟️ Premium: {prem_status}"
        )
        await callback.message.edit_text(text, reply_markup=admin_user_actions_kb(telegram_id, user.is_premium))
        await callback.answer()
    elif len(parts) == 4:
        action = parts[3]
        if action == "grant":
            await user_service.activate_premium(telegram_id, 30)
            await callback.answer("Premium granted for 30 days!", show_alert=True)
        elif action == "revoke":
            await user_service.revoke_premium(telegram_id)
            await callback.answer("Premium revoked!", show_alert=True)
        elif action == "reset":
            await user_service.reset_search_count(telegram_id)
            await callback.answer("Search count reset!", show_alert=True)
        await cb_admin_user_actions(callback)

@router.callback_query(F.data.startswith("adm:docs:"))
async def cb_admin_docs(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    per_page = 5
    async with get_session() as session:
        total = (await session.execute(select(func.count(Document.id)))).scalar() or 0
        result = await session.execute(select(Document).order_by(Document.created_at.desc()).offset((page - 1) * per_page).limit(per_page))
        docs = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)
    await callback.message.edit_text(f"📄 <b>Documents Management</b> ({total} total)\nSelect a document:", reply_markup=admin_docs_kb(docs, page, total_pages, "adm:docs"))
    await callback.answer()

@router.callback_query(F.data.startswith("adm:pend:"))
async def cb_admin_pending(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    per_page = 5
    async with get_session() as session:
        total = (await session.execute(select(func.count(Document.id)).where(Document.approved == False))).scalar() or 0
        result = await session.execute(select(Document).where(Document.approved == False).order_by(Document.created_at.desc()).offset((page - 1) * per_page).limit(per_page))
        docs = result.scalars().all()
    if not docs:
        await callback.answer("No pending documents!", show_alert=True)
        return
    total_pages = max(1, (total + per_page - 1) // per_page)
    await callback.message.edit_text(f"⏳ <b>Pending Approval</b> ({total} total)\nSelect a document:", reply_markup=admin_docs_kb(docs, page, total_pages, "adm:pend"))
    await callback.answer()

@router.callback_query(F.data.startswith("adm:doc:"))
async def cb_admin_doc_actions(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    doc_id = int(parts[2])
    if len(parts) == 3:
        async with get_session() as session:
            doc = await doc_service.get_document_by_id(session, doc_id)
        if not doc:
            await callback.answer("Document not found.", show_alert=True)
            return
        text = (
            f"📄 <b>Document Details</b>\n\n"
            f"🆔 ID: <code>{doc.id}</code>\n"
            f"📁 Name: {sanitise_text(doc.file_name, 100)}\n"
            f"📚 Subject: {doc.subject or 'N/A'}\n"
            f"🏷️ Category: {doc.category or 'N/A'}\n"
            f"✅ Approved: {'Yes' if doc.approved else 'No'}\n"
        )
        await callback.message.edit_text(text, reply_markup=admin_doc_actions_kb(doc.id, doc.approved))
        await callback.answer()
    elif len(parts) == 4:
        action = parts[3]
        if action == "approve":
            async with get_session() as session: await doc_service.approve_document(session, doc_id)
            await callback.answer("Document approved!", show_alert=True)
        elif action == "delete":
            async with get_session() as session: await doc_service.delete_document(session, doc_id)
            await callback.answer("Document deleted!", show_alert=True)
            callback.data = "adm:docs:1"
            await cb_admin_docs(callback)
            return
        await cb_admin_doc_actions(callback, bot)
