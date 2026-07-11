{#
  The D22 HR-band range predicate, rendered once instead of hand-written
  wherever the hr_bands seed is joined — the same shape as
  temperature_band_range (v1.3). The seed remains the single definition
  of the band BOUNDS; this macro centralizes only the null-tolerant
  range test (the open-ended edge bands leave min or max NULL). Callers
  pass an integer-valued expression (round the numeric hr_bpm first) so
  the seed's integer bounds cannot leave a fractional gap.
#}
{% macro hr_band_range(hr_expression, bands_alias='bands') -%}
({{ bands_alias }}.min_hr_bpm is null
        or {{ hr_expression }} >= {{ bands_alias }}.min_hr_bpm)
    and ({{ bands_alias }}.max_hr_bpm is null
        or {{ hr_expression }} <= {{ bands_alias }}.max_hr_bpm)
{%- endmacro %}
