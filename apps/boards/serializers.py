"""게시판 API의 serializer."""

from rest_framework import serializers

from .models import BoardComment, BoardFile, BoardLike, BoardPost


class BoardPostListSerializer(serializers.ModelSerializer):
    """게시글 목록용 serializer.

    목록에서는 본문 전체를 제외하고 카운트/공지/고정 상태를 중심으로 내려줍니다.
    """

    author_name = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = BoardPost
        fields = [
            "id",
            "author",
            "author_name",
            "board_type",
            "title",
            "is_notice",
            "is_pinned",
            "view_count",
            "like_count",
            "comment_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["author", "view_count", "like_count", "comment_count", "created_at", "updated_at"]


class BoardPostDetailSerializer(BoardPostListSerializer):
    """게시글 상세용 serializer. 본문 content를 포함합니다."""

    class Meta(BoardPostListSerializer.Meta):
        fields = BoardPostListSerializer.Meta.fields + ["content"]


class BoardPostCreateUpdateSerializer(serializers.ModelSerializer):
    """게시글 생성/수정 serializer.

    author는 클라이언트가 보내지 않고 request.user로 자동 저장합니다.
    """

    class Meta:
        model = BoardPost
        fields = ["board_type", "title", "content", "is_notice", "is_pinned"]

    def create(self, validated_data):
        return BoardPost.objects.create(author=self.context["request"].user, **validated_data)


class BoardPostPinSerializer(serializers.ModelSerializer):
    """게시글 고정 여부만 수정하는 serializer."""

    class Meta:
        model = BoardPost
        fields = ["is_pinned"]


class BoardCommentSerializer(serializers.ModelSerializer):
    """게시글 댓글 serializer."""

    author_name = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = BoardComment
        fields = ["id", "post", "author", "author_name", "parent", "content", "is_deleted", "created_at", "updated_at"]
        read_only_fields = ["post", "author", "is_deleted", "created_at", "updated_at"]


class BoardLikeSerializer(serializers.ModelSerializer):
    """좋아요 이력 serializer."""

    class Meta:
        model = BoardLike
        fields = ["id", "post", "user", "created_at"]
        read_only_fields = ["post", "user", "created_at"]


class BoardFileSerializer(serializers.ModelSerializer):
    """게시글 첨부파일 연결 serializer."""

    original_name = serializers.CharField(source="media_file.original_name", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = BoardFile
        fields = ["id", "post", "media_file", "original_name", "download_url", "uploaded_by", "created_at"]
        read_only_fields = ["post", "uploaded_by", "created_at"]

    def get_download_url(self, obj):
        """프론트가 사용할 다운로드 API 경로를 만듭니다."""
        request = self.context.get("request")
        url = f"/api/media/files/{obj.media_file_id}/download/"
        return request.build_absolute_uri(url) if request else url
