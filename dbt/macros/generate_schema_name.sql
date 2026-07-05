{#
  Use +schema values exactly. dbt's default renders custom schemas as
  "<target_schema>_<custom_schema>" (e.g. staging_intermediate), which
  would violate the five locked schema names in decision D3.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
