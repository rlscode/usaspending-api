from django.core.management.base import BaseCommand
from pyspark.sql import SparkSession

from usaspending_api.common.helpers.spark_helpers import (
    configure_spark_session,
    get_active_spark_session,
    get_jvm_logger,
)


class Command(BaseCommand):

    help = """
    This command simply updates the int.award table on databricks with subaward counts based on rpt.subaward_search
    """

    # Values defined in the handler
    destination_database: str
    destination_table_name: str
    spark: SparkSession

    def handle(self, *args, **options):
        extra_conf = {
            # Config for Delta Lake tables and SQL. Need these to keep Dela table metadata in the metastore
            "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
            "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            # See comment below about old date and time values cannot parsed without these
            "spark.sql.legacy.parquet.datetimeRebaseModeInWrite": "LEGACY",  # for dates at/before 1900
            "spark.sql.legacy.parquet.int96RebaseModeInWrite": "LEGACY",  # for timestamps at/before 1900
            "spark.sql.jsonGenerator.ignoreNullFields": "false",  # keep nulls in our json
        }

        self.spark = get_active_spark_session()
        spark_created_by_command = False
        if not self.spark:
            spark_created_by_command = True
            self.spark = configure_spark_session(**extra_conf, spark_context=self.spark)  # type: SparkSession

        # Setup Logger
        logger = get_jvm_logger(self.spark, __name__)

        # Resolve Parameters
        update_award_query = """
            WITH subaward_totals AS (
                SELECT
                    award_id,
                    SUM(COALESCE(subaward_amount, 0)) AS total_subaward_amount,
                    COUNT(*) AS subaward_count
                FROM
                    rpt.subaward_search
                GROUP BY
                    award_id
            )
            MERGE INTO
                raw.awards AS a
                    USING subaward_totals st
                        ON (a.id=st.award_id)
                WHEN matched THEN
                    UPDATE SET
                        a.total_subaward_amount=st.total_subaward_amount,
                        a.subaward_count=COALESCE(st.subaward_count, 0)
        """
        logger.info(f"Updating int.award columns () based on rpt.subaward_search.")
        self.spark.sql(update_award_query)
        logger.info(f"int.award updated.")

        if spark_created_by_command:
            self.spark.stop()
