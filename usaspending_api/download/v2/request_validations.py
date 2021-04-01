from copy import deepcopy
from datetime import datetime, MINYEAR, MAXYEAR
from django.conf import settings
from typing import Optional

from usaspending_api.awards.models import Award
from usaspending_api.awards.v2.lookups.lookups import (
    all_subaward_types,
    assistance_type_mapping,
    award_type_mapping,
    contract_type_mapping,
    idv_type_mapping,
    grant_type_mapping,
    direct_payment_type_mapping,
    loan_type_mapping,
    other_type_mapping,
)
from usaspending_api.common.exceptions import InvalidParameterException
from usaspending_api.common.helpers import fiscal_year_helpers as fy_helpers
from usaspending_api.common.validator.award_filter import AWARD_FILTER_NO_RECIPIENT_ID
from usaspending_api.common.validator.tinyshield import TinyShield
from usaspending_api.download.helpers import check_types_and_assign_defaults, get_date_range_length
from usaspending_api.download.lookups import (
    ACCOUNT_FILTER_DEFAULTS,
    FILE_FORMATS,
    VALID_ACCOUNT_SUBMISSION_TYPES,
)
from usaspending_api.references.models import DisasterEmergencyFundCode, ToptierAgency
from usaspending_api.submissions import helpers as sub_helpers


class DownloadValidatorBase:
    name: str

    def __init__(self, request_data: dict):
        self.common_tinyshield_models = [
            {
                "name": "columns",
                "key": "columns",
                "type": "array",
                "array_type": "text",
                "text_type": "search",
                "min": 0,
            },
            {
                "name": "file_format",
                "key": "file_format",
                "type": "enum",
                "enum_values": ["csv", "tsv", "pstxt"],
                "default": "csv",
            },
        ]
        self._json_request = {
            "file_format": request_data.get("file_format", "csv").lower(),
        }
        if request_data.get("columns"):
            self._json_request["columns"] = request_data.get("columns")

        self.tinyshield_models = []

    def get_validated_request(self):
        models = self.tinyshield_models + self.common_tinyshield_models
        validated_request = TinyShield(models).block(self._json_request)
        validated_request["request_type"] = self.name
        return validated_request

    def set_filter_defaults(self, defaults: dict):
        for key, val in defaults.items():
            self._json_request["filters"].setdefault(key, val)

    @property
    def json_request(self):
        return deepcopy(self._json_request)


class AwardDownloadValidator(DownloadValidatorBase):
    name = "award"

    def __init__(self, request_data: dict):
        super().__init__(request_data)
        self.request_data = request_data
        self._json_request["download_types"] = self.request_data.get("award_levels")
        self._json_request["filters"] = _validate_filters_exist(request_data)
        self.set_filter_defaults({"award_type_codes": list(award_type_mapping.keys())})

        constraint_type = self.request_data.get("constraint_type")
        if constraint_type == "year" and sorted(self._json_request["filters"]) == ["award_type_codes", "keywords"]:
            self._handle_keyword_search_download()
        elif constraint_type == "year":
            self._handle_custom_award_download()
        elif constraint_type == "row_count":
            self._handle_advanced_search_download()
        else:
            raise InvalidParameterException('Invalid parameter: constraint_type must be "row_count" or "year"')

    def _handle_keyword_search_download(self):
        # Overriding all other filters if the keyword filter is provided in year-constraint download
        self._json_request["filters"] = {"elasticsearch_keyword": self._json_request["filters"]["keywords"]}

        self.tinyshield_models.extend(
            [
                {
                    "name": "elasticsearch_keyword",
                    "key": "filters|elasticsearch_keyword",
                    "type": "array",
                    "array_type": "text",
                    "text_type": "search",
                },
                {
                    "name": "download_types",
                    "key": "download_types",
                    "type": "array",
                    "array_type": "enum",
                    "enum_values": ["prime_awards"],
                },
            ]
        )
        self._json_request = self.get_validated_request()
        self._json_request["limit"] = settings.MAX_DOWNLOAD_LIMIT
        self._json_request["filters"]["award_type_codes"] = list(award_type_mapping)

    def _handle_custom_award_download(self):
        """
        Custom Award Download allows different filters than other Award Download Endpoints
        and thus it needs to be normalized before moving forward
        # TODO: Refactor to use similar filters as Advanced Search download
        """
        self.tinyshield_models.extend(
            [
                {
                    "name": "agencies",
                    "key": "filters|agencies",
                    "type": "array",
                    "array_type": "object",
                    "object_keys": {
                        "type": {"type": "enum", "enum_values": ["funding", "awarding"], "optional": False},
                        "tier": {"type": "enum", "enum_values": ["toptier", "subtier"], "optional": False},
                        "toptier_name": {"type": "text", "text_type": "search", "optional": True},
                        "name": {"type": "text", "text_type": "search", "optional": False},
                    },
                },
                {"name": "agency", "key": "filters|agency", "type": "integer"},
                {
                    "name": "date_range",
                    "key": "filters|date_range",
                    "type": "object",
                    "optional": False,
                    "object_keys": {
                        "start_date": {"type": "date", "default": "1000-01-01"},
                        "end_date": {"type": "date", "default": datetime.strftime(datetime.utcnow(), "%Y-%m-%d")},
                    },
                },
                {
                    "name": "date_type",
                    "key": "filters|date_type",
                    "type": "enum",
                    "enum_values": ["action_date", "last_modified_date"],
                    "default": "action_date",
                },
                {
                    "name": "place_of_performance_locations",
                    "key": "filters|place_of_performance_locations",
                    "type": "array",
                    "array_type": "object",
                    "object_keys": {
                        "country": {"type": "text", "text_type": "search", "optional": False},
                        "state": {"type": "text", "text_type": "search", "optional": True},
                        "zip": {"type": "text", "text_type": "search", "optional": True},
                        "district": {"type": "text", "text_type": "search", "optional": True},
                        "county": {"type": "text", "text_type": "search", "optional": True},
                        "city": {"type": "text", "text_type": "search", "optional": True},
                    },
                },
                {
                    "name": "place_of_performance_scope",
                    "key": "filters|place_of_performance_scope",
                    "type": "enum",
                    "enum_values": ["domestic", "foreign"],
                },
                {
                    "name": "prime_award_types",
                    "key": "filters|prime_award_types",
                    "type": "array",
                    "array_type": "enum",
                    "min": 0,
                    "enum_values": list(award_type_mapping.keys()),
                },
                {
                    "name": "recipient_locations",
                    "key": "filters|recipient_locations",
                    "type": "array",
                    "array_type": "object",
                    "object_keys": {
                        "country": {"type": "text", "text_type": "search", "optional": False},
                        "state": {"type": "text", "text_type": "search", "optional": True},
                        "zip": {"type": "text", "text_type": "search", "optional": True},
                        "district": {"type": "text", "text_type": "search", "optional": True},
                        "county": {"type": "text", "text_type": "search", "optional": True},
                        "city": {"type": "text", "text_type": "search", "optional": True},
                    },
                },
                {
                    "name": "recipient_scope",
                    "key": "filters|recipient_scope",
                    "type": "enum",
                    "enum_values": ("domestic", "foreign"),
                },
                {"name": "sub_agency", "key": "filters|sub_agency", "type": "text", "text_type": "search"},
                {
                    "name": "sub_award_types",
                    "key": "filters|sub_award_types",
                    "type": "array",
                    "array_type": "enum",
                    "min": 0,
                    "enum_values": all_subaward_types,
                },
            ]
        )

        filter_all_agencies = False
        if str(self._json_request["filters"].get("agency", "")).lower() == "all":
            filter_all_agencies = True
            self._json_request["filters"].pop("agency")

        self._json_request = self.get_validated_request()
        custom_award_filters = self._json_request["filters"]
        final_award_filters = {}

        # These filters do not need any normalization
        for key, value in custom_award_filters.items():
            if key in [
                "recipient_locations",
                "recipient_scope",
                "place_of_performance_location",
                "place_of_performance_scope",
            ]:
                final_award_filters[key] = value

        if get_date_range_length(custom_award_filters["date_range"]) > 366:
            raise InvalidParameterException("Invalid Parameter: date_range total days must be within a year")

        final_award_filters["time_period"] = [
            {**custom_award_filters["date_range"], "date_type": custom_award_filters["date_type"]}
        ]

        if (
            custom_award_filters.get("prime_award_types") is None
            and custom_award_filters.get("sub_award_types") is None
        ):
            raise InvalidParameterException(
                "Missing one or more required body parameters: prime_award_types or sub_award_types"
            )

        self._json_request["download_types"] = []
        final_award_filters["prime_and_sub_award_types"] = {}

        if custom_award_filters.get("prime_award_types"):
            self._json_request["download_types"].append("prime_awards")
            final_award_filters["prime_and_sub_award_types"]["prime_awards"] = custom_award_filters["prime_award_types"]

        if custom_award_filters.get("sub_award_types"):
            self._json_request["download_types"].append("sub_awards")
            final_award_filters["prime_and_sub_award_types"]["sub_awards"] = custom_award_filters["sub_award_types"]

        if "agency" in custom_award_filters:
            if "agencies" not in custom_award_filters:
                final_award_filters["agencies"] = []

            if filter_all_agencies:
                toptier_name = "all"
            else:
                toptier_name = (
                    ToptierAgency.objects.filter(toptier_agency_id=custom_award_filters["agency"])
                    .values("name")
                    .first()
                )
                if toptier_name is None:
                    raise InvalidParameterException(f"Toptier ID not found: {custom_award_filters['agency']}")
                toptier_name = toptier_name["name"]

            if "sub_agency" in custom_award_filters:
                final_award_filters["agencies"].append(
                    {
                        "type": "awarding",
                        "tier": "subtier",
                        "name": custom_award_filters["sub_agency"],
                        "toptier_name": toptier_name,
                    }
                )
            else:
                final_award_filters["agencies"].append({"type": "awarding", "tier": "toptier", "name": toptier_name})

        if "agencies" in custom_award_filters:
            final_award_filters["agencies"] = [
                val for val in custom_award_filters["agencies"] if val.get("name", "").lower() != "all"
            ]

        self._json_request["filters"] = final_award_filters

    def _handle_advanced_search_download(self):
        self.tinyshield_models.extend(
            [
                *AWARD_FILTER_NO_RECIPIENT_ID,
                {
                    "name": "limit",
                    "key": "limit",
                    "type": "integer",
                    "min": 0,
                    "max": settings.MAX_DOWNLOAD_LIMIT,
                    "default": settings.MAX_DOWNLOAD_LIMIT,
                },
                {
                    "name": "download_types",
                    "key": "download_types",
                    "type": "array",
                    "array_type": "enum",
                    "enum_values": ["elasticsearch_awards", "sub_awards", "elasticsearch_transactions", "prime_awards"],
                },
            ]
        )
        self._json_request["limit"] = self.request_data.get("limit", settings.MAX_DOWNLOAD_LIMIT)
        self._json_request = self.get_validated_request()


class IdvDownloadValidator(DownloadValidatorBase):
    name = "idv"

    def __init__(self, request_data: dict):
        super().__init__(request_data)
        self.tinyshield_models.extend(
            [
                {
                    "key": "award_id",
                    "name": "award_id",
                    "type": "any",
                    "models": [{"type": "integer"}, {"type": "text", "text_type": "raw"}],
                    "optional": False,
                    "allow_nulls": False,
                },
                {
                    "name": "limit",
                    "key": "limit",
                    "type": "integer",
                    "min": 0,
                    "max": settings.MAX_DOWNLOAD_LIMIT,
                    "default": settings.MAX_DOWNLOAD_LIMIT,
                },
            ]
        )
        self._json_request = request_data
        self._json_request = self.get_validated_request()
        award_id, piid, _, _, _ = _validate_award_id(self._json_request.pop("award_id"))
        filters = {
            "idv_award_id": award_id,
            "award_type_codes": tuple(set(contract_type_mapping) | set(idv_type_mapping)),
        }
        self._json_request.update(
            {
                "account_level": "treasury_account",
                "download_types": ["idv_orders", "idv_transaction_history", "idv_federal_account_funding"],
                "include_file_description": {
                    "source": settings.IDV_DOWNLOAD_README_FILE_PATH,
                    "destination": "readme.txt",
                },
                "piid": piid,
                "is_for_idv": True,
                "filters": filters,
                "include_data_dictionary": True,
            }
        )


class ContractDownloadValidator(DownloadValidatorBase):
    name = "contract"

    def __init__(self, request_data: dict):
        super().__init__(request_data)
        self.tinyshield_models.extend(
            [
                {
                    "key": "award_id",
                    "name": "award_id",
                    "type": "any",
                    "models": [{"type": "integer"}, {"type": "text", "text_type": "raw"}],
                    "optional": False,
                    "allow_nulls": False,
                },
                {
                    "name": "limit",
                    "key": "limit",
                    "type": "integer",
                    "min": 0,
                    "max": settings.MAX_DOWNLOAD_LIMIT,
                    "default": settings.MAX_DOWNLOAD_LIMIT,
                },
            ]
        )
        self._json_request = request_data
        self._json_request = self.get_validated_request()
        award_id, piid, _, _, _ = _validate_award_id(self._json_request.pop("award_id"))
        filters = {
            "award_id": award_id,
            "award_type_codes": tuple(set(contract_type_mapping)),
        }
        self._json_request.update(
            {
                "account_level": "treasury_account",
                "download_types": ["sub_contracts", "contract_transactions", "contract_federal_account_funding"],
                "include_file_description": {
                    "source": settings.CONTRACT_DOWNLOAD_README_FILE_PATH,
                    "destination": "ContractAwardSummary_download_readme.txt",
                },
                "award_id": award_id,
                "piid": piid,
                "is_for_idv": False,
                "is_for_contract": True,
                "is_for_assistance": False,
                "filters": filters,
                "include_data_dictionary": True,
            }
        )


class AssistanceDownloadValidator(DownloadValidatorBase):
    name = "assistance"

    def __init__(self, request_data: dict):
        super().__init__(request_data)
        self.tinyshield_models.extend(
            [
                {
                    "key": "award_id",
                    "name": "award_id",
                    "type": "any",
                    "models": [{"type": "integer"}, {"type": "text", "text_type": "raw"}],
                    "optional": False,
                    "allow_nulls": False,
                },
                {
                    "name": "limit",
                    "key": "limit",
                    "type": "integer",
                    "min": 0,
                    "max": settings.MAX_DOWNLOAD_LIMIT,
                    "default": settings.MAX_DOWNLOAD_LIMIT,
                },
            ]
        )
        self._json_request = request_data
        self._json_request = self.get_validated_request()
        award_id, _, fain, uri, generated_unique_award_id = _validate_award_id(self._json_request.pop("award_id"))
        filters = {
            "award_id": award_id,
            "award_type_codes": tuple(set(assistance_type_mapping)),
        }
        award = fain
        if "AGG" in generated_unique_award_id:
            award = uri

        self._json_request.update(
            {
                "account_level": "treasury_account",
                "download_types": ["assistance_transactions", "sub_grants", "assistance_federal_account_funding"],
                "include_file_description": {
                    "source": settings.ASSISTANCE_DOWNLOAD_README_FILE_PATH,
                    "destination": "AssistanceAwardSummary_download_readme.txt",
                },
                "award_id": award_id,
                "assistance_id": award,
                "is_for_idv": False,
                "is_for_contract": False,
                "is_for_assistance": True,
                "filters": filters,
                "include_data_dictionary": True,
            }
        )


class DisasterRecipientDownloadValidator(DownloadValidatorBase):
    name = "disaster_recipient"

    def __init__(self, request_data: dict):
        super().__init__(request_data)
        self.tinyshield_models.extend(
            [
                {
                    "key": "filters|def_codes",
                    "name": "def_codes",
                    "type": "array",
                    "array_type": "enum",
                    "enum_values": sorted(DisasterEmergencyFundCode.objects.values_list("code", flat=True)),
                    "allow_nulls": False,
                    "optional": False,
                },
                {
                    "key": "filters|query",
                    "name": "query",
                    "type": "text",
                    "text_type": "search",
                    "allow_nulls": False,
                    "optional": True,
                },
                {
                    "key": "filters|award_type_codes",
                    "name": "award_type_codes",
                    "type": "array",
                    "array_type": "enum",
                    "enum_values": sorted(award_type_mapping.keys()),
                    "allow_nulls": False,
                    "optional": True,
                },
            ]
        )
        self._json_request["filters"] = request_data.get("filters")
        self._json_request = self.get_validated_request()
        self._json_request["download_types"] = [self.name]

        # Determine what to use in the filename based on "award_type_codes" filter;
        # Also add "face_value_of_loans" column if only loan types
        award_category = "All-Awards"
        award_type_codes = set(self._json_request["filters"].get("award_type_codes", award_type_mapping.keys()))
        columns = ["recipient", "award_obligations", "award_outlays", "number_of_awards"]

        if award_type_codes <= set(contract_type_mapping.keys()):
            award_category = "Contracts"
        elif award_type_codes <= set(idv_type_mapping.keys()):
            award_category = "Contract-IDVs"
        elif award_type_codes <= set(grant_type_mapping.keys()):
            award_category = "Grants"
        elif award_type_codes <= set(loan_type_mapping.keys()):
            award_category = "Loans"
            columns.insert(3, "face_value_of_loans")
        elif award_type_codes <= set(direct_payment_type_mapping.keys()):
            award_category = "Direct-Payments"
        elif award_type_codes <= set(other_type_mapping.keys()):
            award_category = "Other-Financial-Assistance"

        self._json_request["award_category"] = award_category
        self._json_request["columns"] = self._json_request.get("columns") or tuple(columns)

        # Need to specify the field to use "query" filter on if present
        query_text = self._json_request["filters"].pop("query", None)
        if query_text:
            self._json_request["filters"]["query"] = {"text": query_text, "fields": ["recipient_name"]}


def validate_account_request(request_data):
    json_request = {"columns": request_data.get("columns", []), "filters": {}}

    _validate_required_parameters(request_data, ["account_level", "filters"])
    json_request["account_level"] = _validate_account_level(request_data, ["federal_account", "treasury_account"])

    filters = _validate_filters_exist(request_data)

    json_request["file_format"] = str(request_data.get("file_format", "csv")).lower()

    _validate_file_format(json_request)

    fy = _validate_fiscal_year(filters)
    quarter = _validate_fiscal_quarter(filters)
    period = _validate_fiscal_period(filters)

    fy, quarter, period = _validate_and_bolster_requested_submission_window(fy, quarter, period)

    json_request["filters"]["fy"] = fy
    json_request["filters"]["quarter"] = quarter
    json_request["filters"]["period"] = period

    _validate_submission_type(filters)

    json_request["download_types"] = request_data["filters"]["submission_types"]
    json_request["agency"] = request_data["filters"]["agency"] if request_data["filters"].get("agency") else "all"

    json_request["filters"]["def_codes"] = _validate_def_codes(filters)

    # Validate the rest of the filters
    check_types_and_assign_defaults(filters, json_request["filters"], ACCOUNT_FILTER_DEFAULTS)

    return json_request


def _validate_award_id(award_id):
    if type(award_id) is int or award_id.isdigit():
        filters = {"id": int(award_id)}
    else:
        filters = {"generated_unique_award_id": award_id}

    award = (
        Award.objects.filter(**filters).values_list("id", "piid", "fain", "uri", "generated_unique_award_id").first()
    )
    if not award:
        raise InvalidParameterException("Unable to find award matching the provided award id")
    return award


def _validate_account_level(request_data, valid_account_levels):
    account_level = request_data.get("account_level")
    if account_level not in valid_account_levels:
        raise InvalidParameterException("Invalid Parameter: account_level must be {}".format(valid_account_levels))
    return account_level


def _validate_filters_exist(request_data):
    filters = request_data.get("filters")
    if not isinstance(filters, dict):
        raise InvalidParameterException("Filters parameter not provided as a dict")
    elif len(filters) == 0:
        raise InvalidParameterException("At least one filter is required.")
    return filters


def _validate_required_parameters(request_data, required_parameters):
    for required_param in required_parameters:
        if required_param not in request_data:
            raise InvalidParameterException("Missing one or more required body parameters: {}".format(required_param))


def _validate_file_format(json_request: dict) -> None:
    val = json_request["file_format"]
    if val not in FILE_FORMATS:
        msg = f"'{val}' is not an acceptable value for 'file_format'. Valid options: {tuple(FILE_FORMATS.keys())}"
        raise InvalidParameterException(msg)


def _validate_fiscal_year(filters: dict) -> int:
    if "fy" not in filters:
        raise InvalidParameterException("Missing required filter 'fy'.")

    try:
        fy = int(filters["fy"])
    except (TypeError, ValueError):
        raise InvalidParameterException("'fy' filter not provided as an integer.")

    if not fy_helpers.is_valid_year(fy):
        raise InvalidParameterException(f"'fy' must be a valid year from {MINYEAR} to {MAXYEAR}.")

    return fy


def _validate_fiscal_quarter(filters: dict) -> Optional[int]:

    if "quarter" not in filters:
        return None

    try:
        quarter = int(filters["quarter"])
    except (TypeError, ValueError):
        raise InvalidParameterException(f"'quarter' filter not provided as an integer.")

    if not fy_helpers.is_valid_quarter(quarter):
        raise InvalidParameterException("'quarter' filter must be a valid fiscal quarter from 1 to 4.")

    return quarter


def _validate_fiscal_period(filters: dict) -> Optional[int]:

    if "period" not in filters:
        return None

    try:
        period = int(filters["period"])
    except (TypeError, ValueError):
        raise InvalidParameterException(f"'period' filter not provided as an integer.")

    if not fy_helpers.is_valid_period(period):
        raise InvalidParameterException(
            "'period' filter must be a valid fiscal period from 2 to 12.  Agencies may not submit for period 1."
        )

    return period


def _validate_def_codes(filters: dict) -> Optional[list]:

    # case when the whole def_codes object is missing from filters
    if "def_codes" not in filters or filters["def_codes"] is None:
        return None

    all_def_codes = sorted(DisasterEmergencyFundCode.objects.values_list("code", flat=True))
    provided_codes = set([str(code).upper() for code in filters["def_codes"]])  # accept lowercase def_code

    if not provided_codes.issubset(all_def_codes):
        raise InvalidParameterException(
            f"provide codes {filters['def_codes']} contain non-valid DEF Codes. List of valid DEFC {','.join(all_def_codes)}"
        )

    return list(provided_codes)


def _validate_and_bolster_requested_submission_window(
    fy: int, quarter: Optional[int], period: Optional[int]
) -> (int, Optional[int], Optional[int]):
    """
    The assumption here is that each of the provided values has been validated independently already.
    Now it's time to validate them as a pair.  We also need to bolster period or quarter since they
    are mutually exclusive in the filter.
    """
    if quarter is None and period is None:
        raise InvalidParameterException("Either 'period' or 'quarter' is required in filters.")

    if quarter is not None and period is not None:
        raise InvalidParameterException("Supply either 'period' or 'quarter' in filters but not both.")

    if period is not None:
        # If period is provided, then we are going to grab the most recently closed quarter in the
        # same fiscal year equal to or less than the period requested.  If there are no closed
        # quarters in the fiscal year matching this criteria then no quarterly submissions will be
        # returned.  So, by way of example, if the user requests P7 and Q2 is closed then we will
        # return P7 monthly and Q2 quarterly submissions.  If Q2 is not closed yet, we will return
        # P7 monthly and Q1 quarterly submissions.  If P2 is requested then we will only return P2
        # monthly submissions since there can be no closed quarter prior to P2 in the same year.
        # Finally, if P3 is requested and Q1 is closed then we will return P3 monthly and Q1 quarterly
        # submissions.  Man I hope that all made sense.
        quarter = sub_helpers.get_last_closed_quarter_relative_to_month(fy, period)

    else:
        # This is the same idea as above, the big difference being that we do not have monthly
        # submissions for earlier years so really this will either return the final period of
        # the quarter or None.
        period = sub_helpers.get_last_closed_month_relative_to_quarter(fy, quarter)

    return fy, quarter, period


def _validate_submission_type(filters: dict) -> None:
    """Validate submission_type/submission_types parameter

    In February 2020 submission_type became the legacy filter, replaced by submission_types
    submission_type was left in-place for backward compatibility but hidden in API Contract and error messages
    """
    legacy_submission_type = filters.get("submission_type", ...)
    submission_types = filters.get("submission_types", ...)

    if submission_types == ... and legacy_submission_type == ...:
        raise InvalidParameterException("Missing required filter: submission_types")

    elif submission_types == ... and legacy_submission_type != ...:
        del filters["submission_type"]
        if isinstance(legacy_submission_type, list):
            raise InvalidParameterException("Use filter `submission_types` to request multiple submission types")
        else:
            submission_types = [legacy_submission_type]
    else:
        if not isinstance(submission_types, list):
            submission_types = [submission_types]

    if len(submission_types) == 0:
        msg = f"Provide at least one value in submission_types: {' '.join(VALID_ACCOUNT_SUBMISSION_TYPES)}"
        raise InvalidParameterException(msg)

    if any(True for submission_type in submission_types if submission_type not in VALID_ACCOUNT_SUBMISSION_TYPES):
        msg = f"Invalid value in submission_types. Options: [{', '.join(VALID_ACCOUNT_SUBMISSION_TYPES)}]"
        raise InvalidParameterException(msg)

    filters["submission_types"] = list(set(submission_types))
