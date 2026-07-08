{#
  The D14 temperature-band range predicate, rendered once instead of
  hand-written in every mart that joins the temperature_bands seed. The
  seed remains the single definition of the band BOUNDS; this macro
  centralizes only the null-tolerant range test (an open-ended band
  leaves min or max NULL). Call-site-specific join conditions
  (weather_available, not is_trainer) stay at the call sites.
#}
{% macro temperature_band_range(temperature_expression, bands_alias='bands') -%}
({{ bands_alias }}.min_temperature_f is null
        or {{ temperature_expression }} >= {{ bands_alias }}.min_temperature_f)
    and ({{ bands_alias }}.max_temperature_f is null
        or {{ temperature_expression }} <= {{ bands_alias }}.max_temperature_f)
{%- endmacro %}
