<template id="page-satspay">
  <div class="row q-col-gutter-md">
    <div class="col-12 col-md-7 q-gutter-y-md">
      <q-card>
        <q-card-section>
          <q-btn
            unelevated
            color="primary"
            :label="$t('satspay.new_charge')"
            @click="formDialogCharge.show = true"
          ></q-btn>

          <q-btn
            v-if="g.user.admin"
            unelevated
            color="primary"
            class="q-ml-md"
            :label="$t('satspay.new_css_theme')"
            @click="formDialogThemes.show = true"
          ></q-btn>
          <q-btn
            v-else
            disable
            unelevated
            color="primary"
            class="q-ml-md"
            :label="$t('satspay.new_css_theme')"
            @click="formDialogThemes.show = true"
          >
            <q-tooltip v-text="$t('satspay.css_admin_only')"></q-tooltip>
          </q-btn>
          <lnbits-extension-settings-btn-dialog
            v-if="g.user.admin"
            :endpoint="endpoint"
            :options="settings"
          ></lnbits-extension-settings-btn-dialog>
        </q-card-section>
      </q-card>

      <q-card>
        <q-card-section>
          <div class="row items-center no-wrap q-mb-md">
            <div class="col">
              <h5
                class="text-subtitle1 q-my-none"
                v-text="$t('satspay.charges')"
              ></h5>
            </div>
            <div class="col q-pr-lg">
              <q-input
                borderless
                dense
                debounce="300"
                v-model="filter"
                :placeholder="$t('satspay.search')"
                class="float-right"
              >
                <template v-slot:append>
                  <q-icon name="search"></q-icon>
                </template>
              </q-input>
            </div>
            <div class="col-auto">
              <q-btn outline color="grey" label="...">
                <q-menu auto-close>
                  <q-list style="min-width: 100px">
                    <q-item clickable>
                      <q-item-section
                        @click="exportchargeCSV"
                        v-text="$t('satspay.export_csv')"
                      ></q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
            </div>
          </div>
          <q-table
            flat
            dense
            :rows="chargeLinks"
            row-key="id"
            :columns="chargesColumns"
            v-model:pagination="chargesTable.pagination"
            :filter="filter"
          >
            <template v-slot:header="props">
              <q-tr :props="props">
                <q-th auto-width></q-th>
                <q-th auto-width v-text="$t('satspay.status')"></q-th>
                <q-th auto-width v-text="$t('satspay.title')"></q-th>
                <q-th auto-width v-text="$t('satspay.time_left')"></q-th>
                <q-th auto-width v-text="$t('satspay.amount')"></q-th>
                <q-th auto-width v-text="$t('satspay.balance')"></q-th>
                <q-th auto-width v-text="$t('satspay.pending')"></q-th>
                <q-th auto-width v-text="$t('satspay.onchain_address')"></q-th>
                <q-th auto-width></q-th>
              </q-tr>
            </template>

            <template v-slot:body="props">
              <q-tr :props="props">
                <q-td auto-width>
                  <q-btn
                    size="sm"
                    color="primary"
                    round
                    dense
                    @click="props.row.expanded = !props.row.expanded"
                    :icon="props.row.expanded ? 'remove' : 'add'"
                  ></q-btn>
                </q-td>

                <q-td auto-width>
                  <q-badge
                    v-if="
                      props.row.time_elapsed &&
                      props.row.balance < props.row.amount
                    "
                    outline
                    color="primary"
                  >
                    <a
                      :href="props.row.displayUrl"
                      target="_blank"
                      style="color: unset; text-decoration: none"
                      v-text="$t('satspay.expired')"
                    ></a>
                  </q-badge>
                  <q-badge
                    v-else-if="props.row.balance >= props.row.amount"
                    outline
                    color="primary"
                  >
                    <a
                      :href="props.row.displayUrl"
                      target="_blank"
                      style="color: unset; text-decoration: none"
                      v-text="$t('satspay.paid')"
                    ></a>
                  </q-badge>
                  <q-badge
                    v-else-if="props.row.timeSecondsLeft <= 0"
                    outline
                    color="primary"
                  >
                    <a
                      :href="props.row.displayUrl"
                      target="_blank"
                      style="color: unset; text-decoration: none"
                      v-text="$t('satspay.expired')"
                    ></a>
                  </q-badge>
                  <q-badge v-else outline color="primary">
                    <a
                      :href="props.row.displayUrl"
                      target="_blank"
                      style="color: unset; text-decoration: none"
                      v-text="$t('satspay.waiting')"
                    ></a>
                  </q-badge>
                </q-td>

                <q-td key="name" :props="props">
                  <a
                    :href="props.row.displayUrl"
                    target="_blank"
                    style="color: unset; text-decoration: none"
                    v-text="props.row.name"
                  ></a>
                </q-td>
                <q-td key="timeLeft" :props="props">
                  <div v-if="props.row.paid">
                    <q-linear-progress :value="1"></q-linear-progress>
                  </div>
                  <div v-else>
                    <div v-text="props.row.timeLeft"></div>
                    <q-linear-progress
                      v-model="props.row.progress"
                      color="secondary"
                    ></q-linear-progress>
                  </div>
                </q-td>
                <q-td key="amount" :props="props">
                  <div v-text="props.row.amount"></div>
                </q-td>
                <q-td key="balance" :props="props">
                  <div v-text="props.row.balance"></div>
                </q-td>
                <q-td key="pending" :props="props">
                  <div
                    v-text="props.row.pending ? props.row.pending : ''"
                  ></div>
                </q-td>
                <q-td key="onchain address" :props="props">
                  <a
                    class="text-secondary"
                    :href="props.row.displayUrl"
                    target="_blank"
                    style="color: unset; text-decoration: none"
                    v-text="props.row.onchainaddress"
                  ></a>
                </q-td>
              </q-tr>

              <q-tr v-show="props.row.expanded" :props="props">
                <q-td colspan="100%">
                  <div style="padding: 12px">
                    <div>
                      <span v-text="$t('satspay.id')"></span>:
                      <span v-text="props.row.id"></span>
                    </div>
                    <div>
                      <span v-text="$t('satspay.description')"></span>:
                      <span v-text="props.row.description"></span>
                    </div>
                    <div v-if="props.row.onchainwallet">
                      <span v-text="$t('satspay.onchain_wallet')"></span>:
                      <span
                        v-text="getOnchainWalletName(props.row.onchainwallet)"
                      ></span>
                    </div>
                    <div v-if="props.row.lnbitswallet">
                      <span v-text="$t('satspay.lnbits_wallet')"></span>:
                      <span
                        v-text="getLNbitsWalletName(props.row.lnbitswallet)"
                      ></span>
                    </div>
                    <div
                      v-if="
                        props.row.completelink || props.row.completelinktext
                      "
                    >
                      <span v-text="$t('satspay.completed_link')"></span>:
                      <a
                        class="text-secondary"
                        :href="props.row.completelink"
                        target="_blank"
                        style="color: unset; text-decoration: none"
                        v-text="
                          props.row.completelinktext || props.row.completelink
                        "
                      ></a>
                    </div>
                    <div v-if="props.row.webhook">
                      <span v-text="$t('satspay.webhook')"></span>:
                      <a
                        class="text-secondary"
                        :href="props.row.webhook"
                        target="_blank"
                        style="color: unset; text-decoration: none"
                        v-text="props.row.webhook"
                      ></a>
                    </div>
                    <div v-if="props.row.webhook">
                      <span v-text="$t('satspay.webhook_response')"></span>:
                      <q-badge
                        v-if="
                          props.row.extra && props.row.extra.webhook_message
                        "
                        @click="
                          showWebhookResponseDialog(
                            props.row.extra.webhook_response
                          )
                        "
                        color="blue"
                        class="cursor-pointer"
                      >
                        <span v-text="props.row.extra.webhook_message"></span>
                      </q-badge>
                      <span
                        v-else
                        v-text="$t('satspay.no_response_yet')"
                      ></span>
                    </div>
                    <div class="row">
                      <q-btn
                        unelevated
                        outline
                        type="a"
                        :href="props.row.displayUrl"
                        target="_blank"
                        class="float-left q-mr-md q-mt-md"
                        :label="$t('satspay.details')"
                      ></q-btn>
                      <q-btn
                        v-if="!props.row.paid"
                        unelevated
                        outline
                        icon="refresh"
                        @click="checkChargeBalance(props.row.id)"
                        class="float-left q-mr-md q-mt-md"
                        :label="$t('satspay.check_charge_balance')"
                      ></q-btn>
                      <q-btn
                        v-if="props.row.paid && props.row.webhook"
                        unelevated
                        outline
                        icon="refresh"
                        @click="sendWebhook(props.row.id)"
                        class="float-left q-mr-md q-mt-md"
                        :label="$t('satspay.resend_webhook')"
                      ></q-btn>
                      <q-btn
                        unelevated
                        color="pink"
                        icon="cancel"
                        @click="deleteChargeLink(props.row.id)"
                        class="float-left q-mr-md q-mt-md"
                        :label="$t('satspay.delete')"
                      ></q-btn>
                    </div>
                  </div>
                </q-td>
              </q-tr>
            </template>
          </q-table>
        </q-card-section>
      </q-card>

      <q-card v-if="g.user.admin">
        <q-card-section>
          <div class="row items-center no-wrap q-mb-md">
            <div class="col">
              <h5
                class="text-subtitle1 q-my-none"
                v-text="$t('satspay.themes')"
              ></h5>
            </div>
          </div>
          <q-table
            dense
            flat
            :rows="themeLinks"
            row-key="id"
            :columns="customCSSColumns"
            v-model:pagination="customCSSTable.pagination"
          >
            <template v-slot:header="props">
              <q-tr :props="props">
                <q-th auto-width></q-th>
                <q-th
                  v-for="col in props.cols"
                  :key="col.name"
                  :props="props"
                  v-text="col.label"
                ></q-th>
              </q-tr>
            </template>
            <template v-slot:body="props">
              <q-tr :props="props">
                <q-td auto-width>
                  <q-btn
                    flat
                    dense
                    size="xs"
                    @click="updateformDialog(props.row.css_id)"
                    icon="edit"
                    color="light-blue"
                  ></q-btn>
                  <q-btn
                    flat
                    dense
                    size="xs"
                    @click="deleteTheme(props.row.css_id)"
                    icon="cancel"
                    color="pink"
                  ></q-btn>
                </q-td>
                <q-td
                  v-for="col in props.cols"
                  :key="col.name"
                  :props="props"
                  v-text="col.value"
                ></q-td>
              </q-tr>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </div>

    <div class="col-12 col-md-5 q-gutter-y-md">
      <q-card>
        <q-card-section>
          <h6
            class="text-subtitle1 q-my-none"
            v-text="$t('satspay.extension_title')"
          ></h6>
        </q-card-section>
        <q-separator></q-separator>
        <q-card-section>
          <p>
            <span v-text="$t('satspay.extension_desc')"></span><br />
            <span v-text="$t('satspay.extension_warning')"></span><br />
            <small>
              Created by,
              <a class="text-secondary" href="https://github.com/benarc"
                >Ben Arc</a
              >,
              <a
                class="text-secondary"
                target="_blank"
                href="https://github.com/motorina0"
                >motorina0</a
              >
            </small>
          </p>
          <a
            class="text-secondary"
            target="_blank"
            href="/docs#/satspay"
            v-text="$t('satspay.swagger_docs')"
          ></a>
        </q-card-section>
      </q-card>
    </div>

    <q-dialog v-model="formDialogCharge.show" position="top">
      <q-card class="q-pa-lg q-pt-xl lnbits__dialog-card">
        <q-form @submit="sendFormDataCharge" class="q-gutter-md">
          <q-input
            filled
            dense
            v-model.trim="formDialogCharge.data.name"
            type="text"
            :label="$t('satspay.charge_title_label')"
          ></q-input>
          <q-input
            filled
            dense
            v-model.trim="formDialogCharge.data.description"
            type="text"
            :label="$t('satspay.charge_description_label')"
          ></q-input>

          <div class="row q-col-gutter-sm">
            <div class="col">
              <q-select
                dense
                :options="currencies"
                v-model="formDialogCharge.data.currency"
                :display-value="formDialogCharge.data.currency || 'satoshis'"
                :label="$t('satspay.currency')"
                :hint="
                  $t('satspay.converted_to_satoshis') +
                  ' ' +
                  (formDialogCharge.data.currency &&
                  fiatRates[formDialogCharge.data.currency]
                    ? `Currently 1 ${formDialogCharge.data.currency} = ${fiatRates[formDialogCharge.data.currency]} ${g.denomination}`
                    : '')
                "
                @update:model-value="updateFiatRate"
              ></q-select>
            </div>
          </div>

          <q-input
            v-if="formDialogCharge.data.currency === 'satoshis'"
            filled
            dense
            v-model.trim="formDialogCharge.data.amount"
            type="number"
            :label="$t('satspay.amount_sats')"
          ></q-input>
          <q-input
            v-if="formDialogCharge.data.currency !== 'satoshis'"
            filled
            dense
            v-model.trim="formDialogCharge.data.currency_amount"
            type="number"
            :label="
              $t('satspay.amount_currency', {
                currency: formDialogCharge.data.currency
              })
            "
            step="0.01"
          ></q-input>

          <q-input
            filled
            dense
            v-model.trim="formDialogCharge.data.time"
            type="number"
            max="1440"
            :label="$t('satspay.mins_valid')"
          ></q-input>

          <div class="row">
            <div class="col">
              <div v-if="walletLinks.length > 0">
                <q-checkbox
                  v-model="formDialogCharge.data.onchain"
                  :label="$t('satspay.onchain')"
                ></q-checkbox>
              </div>
              <div v-else>
                <q-checkbox
                  :value="false"
                  :label="$t('satspay.onchain')"
                  disabled
                >
                  <q-tooltip
                    v-text="$t('satspay.onchain_wallet_tooltip')"
                  ></q-tooltip>
                </q-checkbox>
              </div>
            </div>
            <div class="col">
              <q-checkbox
                v-model="formDialogCharge.data.lnbits"
                :label="$t('satspay.lnbits_wallet_label')"
              ></q-checkbox>
            </div>
          </div>

          <div v-if="formDialogCharge.data.onchain">
            <q-select
              filled
              dense
              emit-value
              v-model="onchainwallet"
              :options="walletLinks"
              :label="$t('satspay.onchain_wallet')"
            ></q-select>
            <q-item
              tag="label"
              v-ripple
              v-if="!formDialogCharge.data.fasttrack"
            >
              <q-item-section avatar top>
                <q-checkbox
                  v-model="formDialogCharge.data.zeroconf"
                ></q-checkbox>
              </q-item-section>
              <q-item-section>
                <q-item-label
                  v-text="$t('satspay.zeroconf_label')"
                ></q-item-label>
                <q-item-label
                  caption
                  v-text="$t('satspay.zeroconf_desc')"
                ></q-item-label>
              </q-item-section>
            </q-item>
            <q-item tag="label" v-ripple v-if="!formDialogCharge.data.zeroconf">
              <q-item-section avatar top>
                <q-checkbox
                  v-model="formDialogCharge.data.fasttrack"
                ></q-checkbox>
              </q-item-section>
              <q-item-section>
                <q-item-label
                  v-text="$t('satspay.fasttrack_label')"
                ></q-item-label>
                <q-item-label
                  caption
                  v-text="$t('satspay.fasttrack_desc')"
                ></q-item-label>
              </q-item-section>
            </q-item>
          </div>

          <q-select
            v-if="formDialogCharge.data.lnbits"
            filled
            dense
            emit-value
            v-model="formDialogCharge.data.lnbitswallet"
            :options="g.user.walletOptions"
            :label="$t('satspay.wallet')"
          ></q-select>

          <q-toggle
            v-model="showAdvanced"
            :label="$t('satspay.show_advanced')"
          ></q-toggle>

          <div v-if="showAdvanced" class="row">
            <div class="col">
              <q-input
                filled
                dense
                v-model.trim="formDialogCharge.data.webhook"
                type="url"
                :label="$t('satspay.webhook_url')"
                class="q-mt-lg"
              ></q-input>
              <q-input
                filled
                dense
                v-model.trim="formDialogCharge.data.completelink"
                type="url"
                :label="$t('satspay.completed_btn_url')"
                class="q-mt-lg"
              ></q-input>
              <q-input
                filled
                dense
                v-model.trim="formDialogCharge.data.completelinktext"
                type="text"
                :label="$t('satspay.completed_btn_text')"
                class="q-mt-lg"
              ></q-input>
              <q-select
                filled
                dense
                emit-value
                v-model="formDialogCharge.data.custom_css"
                :options="themeOptions"
                :label="$t('satspay.custom_css_theme')"
                class="q-mt-lg"
              ></q-select>
            </div>
          </div>

          <div class="row q-mt-lg">
            <q-btn
              unelevated
              color="primary"
              :disable="
                formDialogCharge.data.time == null ||
                (formDialogCharge.data.amount == null &&
                  formDialogCharge.data.currency_amount == null)
              "
              type="submit"
              :label="$t('satspay.create_charge')"
            ></q-btn>
            <q-btn
              flat
              color="grey"
              class="q-ml-auto"
              @click="cancelCharge"
              :label="$t('satspay.cancel')"
            ></q-btn>
          </div>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="formDialogThemes.show" position="top">
      <q-card class="q-pa-lg q-pt-xl lnbits__dialog-card">
        <q-form @submit="sendFormDataThemes" class="q-gutter-md">
          <q-input
            filled
            dense
            v-model.trim="formDialogThemes.data.title"
            type="text"
            :label="$t('satspay.theme_title')"
          ></q-input>
          <q-input
            filled
            dense
            v-model.trim="formDialogThemes.data.custom_css"
            type="textarea"
            :label="$t('satspay.custom_css')"
          ></q-input>
          <div class="row q-mt-lg">
            <q-btn
              v-if="formDialogThemes.data.css_id"
              unelevated
              color="primary"
              type="submit"
              :label="$t('satspay.update_css_theme')"
            ></q-btn>
            <q-btn
              v-else
              unelevated
              color="primary"
              type="submit"
              :label="$t('satspay.save_css_theme')"
            ></q-btn>
            <q-btn
              flat
              color="grey"
              class="q-ml-auto"
              @click="cancelThemes"
              :label="$t('satspay.cancel')"
            ></q-btn>
          </div>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="showWebhookResponse" position="top">
      <q-card class="q-pa-lg q-pt-xl lnbits__dialog-card">
        <q-input
          filled
          dense
          readonly
          v-model.trim="webhookResponse"
          type="textarea"
          :label="$t('satspay.response')"
        ></q-input>
        <div class="row q-mt-lg">
          <q-btn
            flat
            v-close-popup
            color="grey"
            class="q-ml-auto"
            :label="$t('satspay.close')"
          ></q-btn>
        </div>
      </q-card>
    </q-dialog>
  </div>
</template>
