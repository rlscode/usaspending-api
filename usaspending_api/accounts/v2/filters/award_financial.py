import datetime
import logging

from django.db.models import Case, CharField, OuterRef, Subquery, When, Value
from django.db.models.functions import Concat

from usaspending_api.accounts.helpers import start_and_end_dates_from_fyq
from usaspending_api.awards.v2.lookups.lookups import contract_type_mapping
from usaspending_api.common.exceptions import InvalidParameterException
from usaspending_api.awards.models import FinancialAccountsByAwards
from usaspending_api.references.models import ToptierAgency

logger = logging.getLogger(__name__)


def award_financial_filter(filters, account_level='treasury_account'):
    query_filters = {}

    # Filter by agency if necessary
    if filters.get('agency', False) and filters['agency'] != 'all':
        agency = ToptierAgency.objects.filter(toptier_agency_id=filters['agency']).first()
        if agency:
            query_filters['treasury_account__agency_id'] = agency.cgac_code
        else:
            raise InvalidParameterException('agency with that ID does not exist')

    # TODO: Filter by federal account
    # federal_account = filters.get('federal_account', False)
    # if federal_account:
    #     query_filters['treasury_account__federal_account__federal_account_code'] = federal_account

    # Filter by Fiscal Year and Quarter
    if filters.get('fy', False) and filters.get('quarter', False):
        # For C files, we want all the data from Q1 through the quarter given in the filter
        filter_dates = start_and_end_dates_from_fyq(filters['fy'], filters['quarter'])
        query_filters['reporting_period_start__gte'] = datetime.date(filters['fy']-1, 10, 1)
        query_filters['reporting_period_end__lte'] = filter_dates[1]
    else:
        raise InvalidParameterException('fy and quarter are required parameters')

    queryset = FinancialAccountsByAwards.objects

    # Derive treasury_account_symbol, allocation_transfer_agency_name, agency_name, federal_account_symbol,
    # and recipient_parent_name
    ata_subquery = ToptierAgency.objects.filter(cgac_code=OuterRef('treasury_account__allocation_transfer_agency_id'))
    agency_name_subquery = ToptierAgency.objects.filter(cgac_code=OuterRef('treasury_account__agency_id'))
    queryset = queryset.annotate(
        treasury_account_symbol=Concat(
            'treasury_account__agency_id',
            Value('-'),
            Case(When(treasury_account__availability_type_code='X', then=Value('X')),
                 default=Concat('treasury_account__beginning_period_of_availability', Value('/'),
                                'treasury_account__ending_period_of_availability'),
                 output_field=CharField()),
            Value('-'),
            'treasury_account__main_account_code',
            Value('-'),
            'treasury_account__sub_account_code',
            output_field=CharField()),
        allocation_transfer_agency_name=Subquery(ata_subquery.values('name')[:1]),
        agency_name=Subquery(agency_name_subquery.values('name')[:1]),
        federal_account_symbol=Concat('treasury_account__federal_account__agency_identifier', Value('-'),
                                      'treasury_account__federal_account__main_account_code'),
        recipient_parent_name=Case(
            When(award__latest_transaction__type__in=list(contract_type_mapping.keys()),
                 then='award__latest_transaction__contract_data__ultimate_parent_legal_enti'),
            default='award__latest_transaction__assistance_data__ultimate_parent_legal_enti',
            output_field=CharField()))

    return queryset.filter(**query_filters)
