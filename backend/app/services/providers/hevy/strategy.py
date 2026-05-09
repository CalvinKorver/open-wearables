from app.services.providers.base_strategy import BaseProviderStrategy, ProviderCapabilities
from app.services.providers.hevy.workouts import HevyWorkouts


class HevyStrategy(BaseProviderStrategy):
    """Hevy provider: API-key authenticated REST workouts (no OAuth)."""

    def __init__(self) -> None:
        super().__init__()
        self.oauth = None
        self.workouts = HevyWorkouts(
            workout_repo=self.workout_repo,
            connection_repo=self.connection_repo,
            provider_name=self.name,
            api_base_url=self.api_base_url,
            oauth=None,
        )
        self.data_247 = None

    @property
    def name(self) -> str:
        return "hevy"

    @property
    def api_base_url(self) -> str:
        return "https://api.hevyapp.com"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(rest_pull=True)

    @property
    def has_cloud_api(self) -> bool:
        """True: Celery sync uses REST + stored API key (no OAuth client)."""
        return True
