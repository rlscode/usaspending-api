drop table if exists temp_load_agencies_toptier_agency;


-- Create a temp table containing toptier agencies as we expect them to look in the final table.
create table
    temp_load_agencies_toptier_agency
as (

    -- CGAC agencies
    select
        now() as create_date,
        now() as update_date,
        cgac_agency_code as cgac_code,
        max(agency_abbreviation) as abbreviation,
        max(agency_name) as name,
        max(mission) as mission,
        max(website) as website,
        max(congressional_justification) as justification,
        max(icon_filename) as icon_filename
    from
        temp_load_agencies_raw_agency
    where
        cgac_agency_code is not null and
        agency_name is not null and
        is_frec is false and (
            -- Only load toptiers that have a subtier or are allowed to be standalone
            subtier_code is not null or
            include_toptier_without_subtier is true
        )
    group by
        cgac_agency_code

    union all

    -- FREC agencies
    select
        now() as create_date,
        now() as update_date,
        frec as cgac_code,
        max(frec_abbreviation) as abbreviation,
        max(frec_entity_description) as name,
        max(mission) as mission,
        max(website) as website,
        max(congressional_justification) as justification,
        max(icon_filename) as icon_filename
    from
        temp_load_agencies_raw_agency
    where
        frec is not null and
        frec_entity_description is not null and
        is_frec is true and (
            -- Only load toptiers that have a subtier or are allowed to be standalone
            subtier_code is not null or
            include_toptier_without_subtier is true
        )
    group by
        frec

);
