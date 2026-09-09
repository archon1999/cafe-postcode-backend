class OfflineTranslationsMixin:
    """Keep all language variants only in Agent snapshots."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get("offline_translations"):
            for field in ("name", "description"):
                if field not in data:
                    continue
                for language in ("uz", "uz_crl", "ru"):
                    key = f"{field}_{language}"
                    if hasattr(instance, key):
                        data[key] = getattr(instance, key)
        return data
