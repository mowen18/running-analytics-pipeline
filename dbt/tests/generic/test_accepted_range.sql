{#
  Fails on non-NULL values outside [min_value, max_value]. NULLs pass by
  design — "missing does not mean zero" also means missing is not
  out-of-range. Kept dependency-free on purpose (no dbt_utils).
#}
{% test accepted_range(model, column_name, min_value=none, max_value=none) %}

select {{ column_name }}
from {{ model }}
where
    {{ column_name }} is not null
    and not (
        true
        {% if min_value is not none %} and {{ column_name }} >= {{ min_value }} {% endif %}
        {% if max_value is not none %} and {{ column_name }} <= {{ max_value }} {% endif %}
    )

{% endtest %}
