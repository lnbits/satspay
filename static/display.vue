<template id="page-satspay-public">
  <div v-if="!charge" class="row justify-center q-mt-xl">
    <q-spinner color="primary" size="3em"></q-spinner>
  </div>
  <div v-else class="row justify-center q-mt-md">
    <div class="col-12 col-sm-10 col-md-8 col-lg-6 col-xl-5">
      <q-card>
        <q-card-section class="text-center">
          <div class="text-h4" v-text="charge.name || 'LNbits SatsPay'"></div>
          <div
            class="text-subtitle1"
            v-for="line in charge.description.split('\n')"
            v-text="line"
          ></div>
        </q-card-section>

        <satspay-time-elapsed :charge="charge"></satspay-time-elapsed>

        <q-card-section>
          <q-list>
            <q-item-label header>
              <span v-text="$t('satspay.charge_id')"></span>:
              <span
                class="text-uppercase text-secondary cursor-pointer"
                @click="utils.copyText(charge.id)"
                v-text="charge.id"
              ></span>
            </q-item-label>
            <q-item dense>
              <q-item-section>
                <q-item-label>
                  <span v-text="$t('satspay.total_to_pay')"></span>:
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge color="blue">
                  <span
                    class="text-subtitle2"
                    v-text="utils.formatBalance(charge.amount, g.denomination)"
                  ></span>
                </q-badge>
              </q-item-section>
            </q-item>
            <q-separator spaced></q-separator>
            <q-item dense>
              <q-item-section>
                <q-item-label>
                  <span v-text="$t('satspay.amount_paid')"></span>:
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge color="orange">
                  <span
                    class="text-subtitle2"
                    v-text="utils.formatBalance(charge.balance, g.denomination)"
                  ></span>
                </q-badge>
              </q-item-section>
            </q-item>
            <q-separator spaced v-if="charge.pending"></q-separator>
            <q-item v-if="charge.pending" dense>
              <q-item-section>
                <q-item-label>
                  <span v-text="$t('satspay.amount_pending')"></span>:
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge color="gray">
                  <span
                    class="text-subtitle2"
                    v-text="utils.formatBalance(charge.pending, g.denomination)"
                  ></span>
                </q-badge>
              </q-item-section>
            </q-item>
            <q-separator spaced></q-separator>
            <q-item dense>
              <q-item-section>
                <q-item-label>
                  <span v-text="$t('satspay.amount_due')"></span>:
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge color="green">
                  <span
                    class="text-subtitle2"
                    v-text="
                      utils.formatBalance(
                        Math.max(0, charge.amount - charge.balance),
                        g.denomination
                      )
                    "
                  ></span>
                </q-badge>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>

        <q-card-section v-if="hasEnded">
          <q-separator></q-separator>
          <div class="row justify-center q-mt-sm">
            <div class="col-sm-10 col-md-8 q-ma-md">
              <div v-if="!charge.timeLeft && !charge.paid">
                <q-icon
                  class="fit"
                  name="block"
                  style="color: #ccc; font-size: 21.4em"
                ></q-icon>
              </div>
              <satspay-paid
                v-else-if="charge.paid"
                :charge="charge"
              ></satspay-paid>
            </div>
          </div>
        </q-card-section>

        <q-card-section v-else>
          <q-tabs
            v-model="tab"
            dense
            class="text-grey"
            active-color="primary"
            indicator-color="primary"
            align="justify"
            narrow-indicator
            inline-label
          >
            <q-tab
              v-if="charge.onchainaddress"
              name="uqr"
              icon="qr_code"
              :label="$t('satspay.uqr_tab')"
            ></q-tab>
            <q-tab
              v-if="charge.payment_request"
              name="ln"
              icon="bolt"
              :label="$t('satspay.ln_tab')"
            ></q-tab>
            <q-tab
              v-if="charge.onchainaddress"
              name="btc"
              icon="link"
              :label="$t('satspay.btc_tab')"
            ></q-tab>
            <q-tab
              v-if="fiatProvidersList.length"
              name="fiat"
              icon="payments"
              :label="$t('satspay.fiat_tab')"
            ></q-tab>
          </q-tabs>
          <q-separator></q-separator>
          <q-tab-panels v-model="tab" animated style="background: none">
            <q-tab-panel name="uqr">
              <div class="row justify-center q-mt-sm">
                <div class="col-sm-10 col-md-8">
                  <satspay-show-qr
                    :charge-amount="charge.amount"
                    :type="'uqr'"
                    :value="unifiedQR"
                    :href="unifiedQR"
                  ></satspay-show-qr>
                </div>
              </div>
            </q-tab-panel>
            <q-tab-panel name="ln" v-if="charge.payment_request">
              <div class="row justify-center q-mt-sm">
                <div class="col-sm-10 col-md-8">
                  <satspay-show-qr
                    :charge-amount="charge.amount"
                    :type="'ln'"
                    :value="'lightning:' + charge.payment_request.toUpperCase()"
                    :href="'lightning:' + charge.payment_request"
                  ></satspay-show-qr>
                </div>
              </div>
            </q-tab-panel>
            <q-tab-panel name="btc">
              <div class="row justify-center q-mt-sm">
                <div class="col-sm-10 col-md-8">
                  <satspay-show-qr
                    :charge-amount="charge.amount"
                    :type="'btc'"
                    :value="charge.onchainaddress"
                    :href="'bitcoin:'+charge.onchainaddress.toUpperCase()+'?amount='+(charge.amount/1e8).toFixed(8)"
                  ></satspay-show-qr>
                </div>
              </div>
            </q-tab-panel>
            <q-tab-panel name="fiat">
              <div class="row justify-center q-mt-sm">
                <div class="col-sm-10 col-md-8 text-center">
                  <template v-for="provider in fiatProvidersList" :key="provider.name">
                    <div class="text-subtitle2 q-mb-sm">
                      <span v-text="$t('satspay.fiat_payment_desc', {amount: formattedFiatAmount, provider: provider.name.charAt(0).toUpperCase() + provider.name.slice(1)})"></span>
                    </div>
                    <q-btn
                      unelevated
                      color="primary"
                      icon="payment"
                      class="q-mr-sm q-mb-sm"
                      @click="payFiat(provider)"
                    >
                      <span v-text="$t('satspay.pay')"></span>
                    </q-btn>
                  </template>
                </div>
              </div>
            </q-tab-panel>
          </q-tab-panels>
        </q-card-section>
      </q-card>
    </div>
  </div>
</template>
