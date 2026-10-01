"""drf-spectacular extensions for custom API fields."""

from drf_spectacular.extensions import OpenApiSerializerFieldExtension


from route_planner.serializers import LocationInputField


class LocationInputFieldExtension(OpenApiSerializerFieldExtension):
    target_class = LocationInputField

    def map_serializer_field(self, auto_schema, direction):
        return {
            "oneOf": [
                {"type": "string", "example": "Dallas, TX"},
                {
                    "type": "object",
                    "properties": {
                        "latitude": {"type": "number", "format": "double"},
                        "longitude": {"type": "number", "format": "double"},
                    },
                    "required": ["latitude", "longitude"],
                },
            ]
        }
