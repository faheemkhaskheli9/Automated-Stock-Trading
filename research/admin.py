from django.contrib import admin

from .models import CompanyFundamental, NewsItem, ResearchSnapshot, SocialMention


@admin.register(NewsItem)
class NewsItemAdmin(admin.ModelAdmin):
    list_display = ("symbol", "exchange", "headline", "source", "published_at", "sentiment")
    list_filter = ("exchange", "source")
    search_fields = ("symbol", "headline")
    date_hierarchy = "published_at"


@admin.register(CompanyFundamental)
class CompanyFundamentalAdmin(admin.ModelAdmin):
    list_display = ("symbol", "exchange", "as_of_report_date", "source")
    list_filter = ("exchange",)
    search_fields = ("symbol",)


@admin.register(SocialMention)
class SocialMentionAdmin(admin.ModelAdmin):
    list_display = ("symbol", "exchange", "platform", "posted_at", "sentiment", "reach")
    list_filter = ("exchange", "platform")
    search_fields = ("symbol",)
    date_hierarchy = "posted_at"


@admin.register(ResearchSnapshot)
class ResearchSnapshotAdmin(admin.ModelAdmin):
    list_display = ("symbol", "exchange", "as_of", "feature_count", "built_at")
    list_filter = ("exchange", "provider_keys")
    search_fields = ("symbol",)
    date_hierarchy = "as_of"

    @admin.display(description="features")
    def feature_count(self, obj):
        return len(obj.features)
