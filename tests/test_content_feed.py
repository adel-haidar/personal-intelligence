import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from private_internet.content.router import get_posts, _POST_SORTS
from private_internet.core.request_context import RequestContext

_CTX = RequestContext(user_id="u1", user_email="u1@example.com", is_admin=True)


def _conn_returning(rows):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = {"count": len(rows)}
    cursor.fetchall.return_value = rows
    conn.cursor.return_value = cursor
    return conn, cursor


class TestGetPostsSort:
    @pytest.mark.anyio
    async def test_rejects_unknown_sort(self):
        with pytest.raises(HTTPException) as exc:
            await get_posts(sort="; DROP TABLE content_posts;", ctx=_CTX)
        assert exc.value.status_code == 422

    @pytest.mark.anyio
    @pytest.mark.parametrize("sort", sorted(_POST_SORTS))
    async def test_known_sorts_hit_vetted_order_by(self, sort):
        conn, cursor = _conn_returning([])
        with patch("private_internet.content.router._connect", return_value=conn):
            result = await get_posts(sort=sort, ctx=_CTX)

        assert result["items"] == []
        select_sql = cursor.execute.call_args_list[-1].args[0]
        assert f"ORDER BY {_POST_SORTS[sort]}" in select_sql
        # creator fields the PULSE PostCard needs are in the join
        assert "creator_slug" in select_sql
        assert "creator_score" in select_sql
        assert "creator_bio" in select_sql
