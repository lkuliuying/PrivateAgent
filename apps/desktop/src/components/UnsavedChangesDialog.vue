<script setup lang="ts">
import PaDialog from "../design/PaDialog.vue";
import PaButton from "../design/PaButton.vue";
import { unsavedChanges, resolveUnsavedChanges } from "../services/unsavedChanges";
</script>

<template>
  <PaDialog :open="unsavedChanges.open" title="模型配置尚未保存" :dismissible="!unsavedChanges.saving" @close="resolveUnsavedChanges('cancel')">
    <p>离开前可以保存配置，或放弃本次修改。密钥草稿仅保留在当前应用内存中。</p>
    <p v-if="unsavedChanges.error" role="alert">{{ unsavedChanges.error }}</p>
    <template #footer>
      <PaButton data-autofocus :disabled="unsavedChanges.saving" @click="resolveUnsavedChanges('cancel')">留在此处</PaButton>
      <PaButton :disabled="unsavedChanges.saving" @click="resolveUnsavedChanges('discard')">放弃更改</PaButton>
      <PaButton variant="primary" :loading="unsavedChanges.saving" @click="resolveUnsavedChanges('save')">保存并继续</PaButton>
    </template>
  </PaDialog>
</template>
